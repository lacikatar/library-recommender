"""The recommender.

One ranking function scores every unread book for a reader by blending four
signals, then diversifies the result and attaches a plain-language reason:

* taste     - similarity to books the reader liked (content model)
* community - "readers who liked what you liked also liked ..." (item-item
              collaborative filtering on everyone's shelves, ratings and loans)
* genres    - the favourite genres picked at sign-up (cold start)
* popular   - a Bayesian-smoothed popularity prior

The blend shifts with how much the engine knows: a brand-new reader gets
genres + popularity, and taste + community take over after a handful of
ratings. Nothing is precomputed into tables; with a catalogue this size a
full ranking takes about a millisecond, so results are always up to date.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .content import BookDoc, ContentModel

RATING_STRENGTH = {5: 1.0, 4: 0.7, 3: 0.15, 2: -0.5, 1: -1.0}
SHELF_STRENGTH = {"read": 0.5, "reading": 0.5, "want": 0.35}
LOAN_STRENGTH = 0.45
VIEW_STRENGTH, VIEW_CAP = 0.08, 0.2
DISMISS_STRENGTH = -0.6

CF_MIN_STRENGTH = 0.3  # views alone do not count as "liked"
CF_SHRINKAGE = 2.0  # damps similarities backed by very few readers
SERIES_BONUS = 0.2
MMR_LAMBDA = 0.8
CANDIDATE_POOL = 60


@dataclass
class Signal:
    """Everything known about one reader and one book."""

    rating: int | None = None
    shelf: str | None = None
    borrowed: bool = False
    views: int = 0
    dismissed: bool = False
    last_at: datetime | None = None

    @property
    def strength(self) -> float:
        if self.rating is not None:
            return RATING_STRENGTH[self.rating]
        if self.dismissed:
            return DISMISS_STRENGTH
        best = min(self.views * VIEW_STRENGTH, VIEW_CAP)
        if self.shelf:
            best = max(best, SHELF_STRENGTH[self.shelf])
        if self.borrowed:
            best = max(best, LOAN_STRENGTH)
        return best

    @property
    def consumed(self) -> bool:
        """True if the book should no longer be recommended to this reader."""
        return bool(self.rating is not None or self.shelf or self.borrowed or self.dismissed)

    def touch(self, when: datetime | None) -> None:
        if when and (self.last_at is None or when > self.last_at):
            self.last_at = when


@dataclass
class Recommendation:
    isbn: str
    score: float
    reason: str
    kind: str  # series | taste | community | genres | popular
    because_isbn: str | None = None
    signals: dict[str, float] = field(default_factory=dict)


class RecommendationEngine:
    def __init__(self, docs: list[BookDoc]):
        self.content = ContentModel(docs)
        self.docs = {d.isbn: d for d in docs}
        self._lock = threading.Lock()
        self._loaded_version = -1
        self.set_interactions({})

    # ------------------------------------------------------------------ data
    def set_interactions(self, by_user: dict[int, dict[str, Signal]]) -> None:
        """Rebuild everything that depends on reader behaviour."""
        n = len(self.content)
        index = self.content.index
        users = sorted(by_user)
        liked = np.zeros((len(users), n))
        rating_sum, rating_count = np.zeros(n), np.zeros(n)
        for row, user_id in enumerate(users):
            for isbn, signal in by_user[user_id].items():
                col = index.get(isbn)
                if col is None:
                    continue
                if signal.strength >= CF_MIN_STRENGTH:
                    liked[row, col] = signal.strength
                if signal.rating is not None:
                    rating_sum[col] += signal.rating
                    rating_count[col] += 1

        # Item-item collaborative similarity: shrunk cosine over "liked" columns.
        norms = np.sqrt((liked**2).sum(axis=0))
        community = (liked.T @ liked) / (np.outer(norms, norms) + CF_SHRINKAGE)
        np.fill_diagonal(community, 0.0)
        top = community.max()
        self._community = community / top if top > 0 else community

        # Popularity: how many readers liked it, plus a Bayesian average rating
        # (a book with one 5-star review should not outrank one with forty 4.6s).
        readers = (liked > 0).sum(axis=0)
        global_mean = rating_sum.sum() / rating_count.sum() if rating_count.sum() else 3.8
        prior = 3.0
        bayes = (prior * global_mean + rating_sum) / (prior + rating_count)
        reach = np.log1p(readers)
        reach = reach / reach.max() if reach.max() > 0 else reach
        popularity = 0.6 * reach + 0.4 * (bayes - 1.0) / 4.0
        self._popularity = popularity - popularity.min()  # so the prior actually discriminates
        self.rating_avg = np.divide(
            rating_sum, rating_count, out=np.zeros(n), where=rating_count > 0
        )
        self.rating_count = rating_count.astype(int)
        self._by_user = by_user

    def refresh(self, version: int, loader) -> None:
        """Reload interactions if anything changed since the last request."""
        if version == self._loaded_version:
            return
        with self._lock:
            if version != self._loaded_version:
                self.set_interactions(loader())
                self._loaded_version = version

    # --------------------------------------------------------------- ranking
    def recommend(
        self,
        user_id: int | None,
        favourite_categories: list[str] | None = None,
        limit: int = 12,
        exclude: set[str] | None = None,
    ) -> list[Recommendation]:
        content = self.content
        n = len(content)
        history = self._by_user.get(user_id, {}) if user_id is not None else {}

        pos_idx, pos_w, neg_idx, neg_w = [], [], [], []
        blocked = np.zeros(n, dtype=bool)
        for isbn, signal in history.items():
            i = content.index.get(isbn)
            if i is None:
                continue
            s = signal.strength
            if s > 0:
                pos_idx.append(i)
                pos_w.append(s)
            elif s < 0:
                neg_idx.append(i)
                neg_w.append(-s)
            if signal.consumed:
                blocked[i] = True
        for isbn in exclude or ():
            if isbn in content.index:
                blocked[content.index[isbn]] = True

        pos_w_arr, neg_w_arr = np.array(pos_w), np.array(neg_w)
        taste, taste_anchor = _affinity(content.similarity, pos_idx, pos_w_arr, neg_idx, neg_w_arr)
        community, community_anchor = _affinity(self._community, pos_idx, pos_w_arr, [], neg_w_arr)

        favourites = favourite_categories or []
        genres = (
            np.clip(content.genre_vectors @ content.genre_vector(favourites), 0, 1)
            if favourites
            else np.zeros(n)
        )
        series, series_name = self._series_continuations(history, blocked)

        parts = {
            "taste": _unit(taste),
            "community": _unit(community),
            "genres": _unit(genres),
            "popular": _unit(self._popularity),
        }
        weights = self._weights(
            evidence=float(sum(pos_w)),
            has_community=bool(parts["community"].max() > 0),
            has_genres=bool(favourites),
        )
        score = sum(weights[k] * parts[k] for k in parts) + SERIES_BONUS * series
        score[blocked] = -np.inf

        chosen = self._diversify(score, limit)
        results = []
        for i in chosen:
            contributions = {k: float(weights[k] * parts[k][i]) for k in parts}
            contributions["series"] = float(SERIES_BONUS * series[i])
            # The next unread book of a series the reader is following explains itself.
            kind = "series" if series[i] == 1.0 else max(contributions, key=contributions.get)
            anchor = None
            if kind == "taste" and pos_idx:
                anchor = content.isbns[pos_idx[taste_anchor[i]]]
            elif kind == "community" and pos_idx:
                anchor = content.isbns[pos_idx[community_anchor[i]]]
            results.append(
                Recommendation(
                    isbn=content.isbns[i],
                    score=float(score[i]),
                    kind=kind,
                    because_isbn=anchor,
                    reason=self._reason(kind, i, anchor, history, favourites, series_name),
                    signals={k: round(v, 4) for k, v in contributions.items()},
                )
            )
        return results

    @staticmethod
    def _weights(evidence: float, has_community: bool, has_genres: bool) -> dict[str, float]:
        # 0 for a new reader; one 5-star rating already gives 0.4; six give 0.8.
        confidence = evidence / (evidence + 1.5)
        w = {
            "taste": 0.45 * confidence,
            "community": 0.35 * confidence if has_community else 0.0,
            "genres": 0.35 * (1 - confidence) + 0.05 if has_genres else 0.0,
            "popular": 0.25 * (1 - confidence) + 0.05,
        }
        total = sum(w.values())
        return {k: v / total for k, v in w.items()}

    def _series_continuations(self, history: dict[str, Signal], blocked: np.ndarray):
        """Boost unread books from series the reader has started and liked."""
        content = self.content
        boost = np.zeros(len(content))
        names: dict[int, str] = {}
        started = {
            self.docs[isbn].series
            for isbn, s in history.items()
            if isbn in self.docs and self.docs[isbn].series and s.strength >= LOAN_STRENGTH
        }
        for name in started:
            unread = [i for i in content.series_members.get(name, []) if not blocked[i]]
            unread.sort(key=lambda i: (content.docs[i].year or 9999, content.docs[i].title))
            for rank, i in enumerate(unread):
                boost[i] = 1.0 if rank == 0 else 0.4
                names[i] = name
        return boost, names

    def _diversify(self, score: np.ndarray, limit: int) -> list[int]:
        """Maximal marginal relevance, and at most one book per series."""
        pool = [int(i) for i in np.argsort(-score)[:CANDIDATE_POOL] if np.isfinite(score[i])]
        if not pool:
            return []
        top, bottom = score[pool[0]], score[pool[-1]]
        span = (top - bottom) or 1.0
        relevance = {i: (score[i] - bottom) / span for i in pool}
        similarity = self.content.similarity
        chosen: list[int] = []
        seen_series: set[str] = set()
        while pool and len(chosen) < limit:
            best = max(
                pool,
                key=lambda i: (
                    MMR_LAMBDA * relevance[i]
                    - (1 - MMR_LAMBDA) * max((similarity[i, j] for j in chosen), default=0.0)
                ),
            )
            pool.remove(best)
            name = self.content.docs[best].series
            if name and name in seen_series:
                continue
            if name:
                seen_series.add(name)
            chosen.append(best)
        return chosen

    def _reason(self, kind, i, anchor, history, favourites, series_name) -> str:
        doc = self.content.docs[i]
        if kind == "series":
            return f"Next up in {series_name[i]}"
        if kind == "taste" and anchor:
            title, signal = self.docs[anchor].title, history[anchor]
            if signal.rating and signal.rating >= 4:
                return f"Because you rated {title} {signal.rating}★"
            if signal.shelf == "want":
                return f"Similar to {title}, on your want-to-read shelf"
            if signal.shelf in ("read", "reading") or signal.borrowed:
                return f"Because you read {title}"
            return f"Because you looked at {title}"
        if kind == "community" and anchor:
            return f"Readers who enjoyed {self.docs[anchor].title} also enjoyed this"
        if kind == "genres":
            shared = [c for c in favourites if c in doc.categories][:2]
            if shared:
                return "Matches your taste for " + " and ".join(shared)
        if self.rating_count[i] >= 3 and self.rating_avg[i] >= 4.0:
            return f"Rated {self.rating_avg[i]:.1f}★ by {self.rating_count[i]} readers"
        return "Popular with other readers"

    # ----------------------------------------------------------- other lists
    def similar(
        self,
        isbn: str,
        limit: int = 8,
        exclude: set[str] | None = None,
        same_series: bool = True,
        min_score: float = 0.0,
    ) -> list[str]:
        """Books to show under "Readers also enjoyed" on a book page."""
        i = self.content.index.get(isbn)
        if i is None:
            return []
        score = 0.65 * self.content.similarity[i] + 0.35 * self._community[i]
        score = score.copy()
        score[i] = -np.inf
        for other in exclude or ():
            if other in self.content.index:
                score[self.content.index[other]] = -np.inf
        own_series = self.content.docs[i].series
        out, per_series = [], {}
        for j in np.argsort(-score):
            if len(out) == limit or not np.isfinite(score[j]) or score[j] <= min_score:
                break
            name = self.content.docs[j].series
            if name:
                if name == own_series and not same_series:
                    continue
                if name != own_series and per_series.get(name, 0) >= 2:
                    continue  # do not let one long series fill the row
                per_series[name] = per_series.get(name, 0) + 1
            out.append(self.content.isbns[j])
        return out

    def popular(
        self, limit: int = 12, exclude: set[str] | None = None, one_per_series: bool = False
    ) -> list[str]:
        out, seen = [], set()
        for i in np.argsort(-self._popularity):
            isbn, name = self.content.isbns[i], self.content.docs[i].series
            if isbn in (exclude or ()):
                continue
            if one_per_series and name:
                if name in seen:
                    continue
                seen.add(name)
            out.append(isbn)
            if len(out) == limit:
                break
        return out

    def favourite_anchors(self, user_id: int, limit: int = 2) -> list[str]:
        """The reader's most recent well-liked books, one per series."""
        history = self._by_user.get(user_id, {})
        liked = [
            (s.last_at or datetime.min, isbn) for isbn, s in history.items() if s.strength >= 0.7
        ]
        anchors, seen = [], set()
        for _, isbn in sorted(liked, reverse=True):
            doc = self.docs.get(isbn)
            if doc is None:
                continue
            key = doc.series or isbn
            if key in seen:
                continue
            seen.add(key)
            anchors.append(isbn)
            if len(anchors) == limit:
                break
        return anchors

    def consumed(self, user_id: int | None) -> set[str]:
        history = self._by_user.get(user_id, {}) if user_id is not None else {}
        return {isbn for isbn, s in history.items() if s.consumed}

    def history(self, user_id: int | None) -> dict[str, Signal]:
        return self._by_user.get(user_id, {}) if user_id is not None else {}

    def personal_scores(self, user_id: int | None, favourites: list[str] | None) -> np.ndarray:
        """Unit-scaled personal relevance for every book (used to tilt search)."""
        n = len(self.content)
        history = self.history(user_id)
        pos = [
            (self.content.index[i], s.strength)
            for i, s in history.items()
            if i in self.content.index and s.strength > 0
        ]
        if pos:
            idx, w = zip(*pos)
            taste, _ = _affinity(self.content.similarity, list(idx), np.array(w), [], np.array([]))
            return _unit(taste)
        if favourites:
            return _unit(
                np.clip(self.content.genre_vectors @ self.content.genre_vector(favourites), 0, 1)
            )
        return np.zeros(n)


def _affinity(similarity, pos_idx, pos_w, neg_idx, neg_w):
    """How close each book is to the reader's liked books.

    Uses the mean of the three strongest matches rather than the mean over
    the whole history, so a reader who loves both epic fantasy and true crime
    gets great picks from each instead of a muddle in between.
    """
    n = similarity.shape[0]
    if not pos_idx:
        return np.zeros(n), np.zeros(n, dtype=int)
    contributions = similarity[:, pos_idx] * pos_w
    k = min(3, len(pos_idx))
    top = np.sort(contributions, axis=1)[:, -k:]
    score = top.mean(axis=1)
    anchor = contributions.argmax(axis=1)
    if neg_idx:
        score = score - 0.5 * (similarity[:, neg_idx] * neg_w).max(axis=1)
    return np.clip(score, 0.0, None), anchor


def _unit(x: np.ndarray) -> np.ndarray:
    top = x.max() if x.size else 0
    return x / top if top > 0 else np.zeros_like(x, dtype=float)
