"""Content model: what each book is *about*.

Three views of a book are combined into one item-item similarity matrix:

* text   - TF-IDF of title + description, compressed with truncated SVD (LSA)
           so that books using different words for the same idea still match
* genres - category sets, weighted by inverse frequency so that sharing
           "Greek Mythology" counts for far more than sharing "Fiction"
* meta   - same series or same author

The catalogue is a few hundred books, so dense NumPy matrices are the right
tool. For a catalogue in the hundreds of thousands the same vectors would go
into an approximate-nearest-neighbour index instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

TEXT_WEIGHT, GENRE_WEIGHT, META_WEIGHT = 0.45, 0.40, 0.15
_WORD = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@dataclass
class BookDoc:
    isbn: str
    title: str
    authors: list[str] = field(default_factory=list)
    series: str | None = None
    categories: list[str] = field(default_factory=list)
    description: str = ""
    year: int | None = None
    pages: int | None = None


class ContentModel:
    def __init__(self, docs: list[BookDoc]):
        self.docs = docs
        self.isbns = [d.isbn for d in docs]
        self.index = {isbn: i for i, isbn in enumerate(self.isbns)}
        n = len(docs)

        # --- text ---------------------------------------------------------
        self._tfidf = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=2 if n >= 50 else 1,
            sublinear_tf=True,
            max_features=30_000,
        )
        self._text = self._tfidf.fit_transform([f"{d.title}. {d.description}" for d in docs])
        k = max(1, min(64, n - 1, self._text.shape[1] - 1))
        self._svd = TruncatedSVD(n_components=k, random_state=0)
        self._latent = normalize(self._svd.fit_transform(self._text))
        text_sim = np.clip(self._latent @ self._latent.T, 0.0, 1.0)

        # --- genres -------------------------------------------------------
        self.categories = sorted({c for d in docs for c in d.categories})
        self.category_index = {c: i for i, c in enumerate(self.categories)}
        membership = np.zeros((n, max(1, len(self.categories))))
        for i, d in enumerate(docs):
            for c in d.categories:
                membership[i, self.category_index[c]] = 1.0
        df = membership.sum(axis=0)
        self._category_idf = np.log((1 + n) / (1 + df)) + 1.0
        self.genre_vectors = normalize(membership * self._category_idf)
        genre_sim = self.genre_vectors @ self.genre_vectors.T

        # --- series / author ---------------------------------------------
        meta_sim = np.zeros((n, n))
        by_series: dict[str, list[int]] = {}
        by_author: dict[str, list[int]] = {}
        for i, d in enumerate(docs):
            if d.series:
                by_series.setdefault(d.series, []).append(i)
            for a in d.authors:
                by_author.setdefault(a, []).append(i)
        for members in by_author.values():
            meta_sim[np.ix_(members, members)] = 0.7
        for members in by_series.values():
            meta_sim[np.ix_(members, members)] = 1.0
        self.series_members = by_series

        self.similarity = TEXT_WEIGHT * text_sim + GENRE_WEIGHT * genre_sim + META_WEIGHT * meta_sim
        np.fill_diagonal(self.similarity, 0.0)

        # --- lookup tables for field matches in search --------------------
        self._title_tokens = [set(tokens(d.title)) for d in docs]
        self._people_tokens = [
            set(tokens(" ".join(d.authors) + " " + (d.series or ""))) for d in docs
        ]

    def __len__(self) -> int:
        return len(self.docs)

    def genre_vector(self, category_names: list[str]) -> np.ndarray:
        """Unit vector for a set of category names (e.g. a reader's favourites)."""
        v = np.zeros(self.genre_vectors.shape[1])
        for name in category_names:
            j = self.category_index.get(name)
            if j is not None:
                v[j] = self._category_idf[j]
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def text_scores(self, query: str) -> np.ndarray:
        """Relevance of every book to a free-text query, in [0, 1]."""
        n = len(self.docs)
        query_tokens = set(tokens(query))
        if not query_tokens:
            return np.zeros(n)

        q = self._tfidf.transform([query])
        lexical = np.asarray((self._text @ q.T).todense()).ravel()
        if q.nnz:
            latent_q = normalize(self._svd.transform(q))
            semantic = np.clip(self._latent @ latent_q.ravel(), 0.0, 1.0)
        else:
            semantic = np.zeros(n)

        # Direct hits on title / author / series should always surface.
        title = np.array([len(query_tokens & t) / len(query_tokens) for t in self._title_tokens])
        people = np.array([len(query_tokens & t) / len(query_tokens) for t in self._people_tokens])

        def scaled(x: np.ndarray) -> np.ndarray:
            top = x.max()
            return x / top if top > 0 else x

        score = 0.35 * scaled(lexical) + 0.20 * scaled(semantic) + 0.30 * title + 0.15 * people
        # Every query word is in the title: the reader almost certainly means this book.
        score = score + 0.3 * (title == 1.0)
        return np.clip(score, 0.0, 1.0)
