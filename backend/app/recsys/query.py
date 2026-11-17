"""Turn a natural-language request into a ranked shortlist of books.

"something like Dune but shorter", "cozy mystery under 300 pages",
"dark academia with a slow-burn romance" ...

This is the retrieval half of the librarian. It needs no API key. When an
LLM is configured it only ever chooses among the books found here, so it
cannot invent a title the library does not own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .content import ContentModel, tokens
from .engine import RecommendationEngine

# How people say it -> how the catalogue files it.
CATEGORY_ALIASES = {
    "sci-fi": "Science Fiction",
    "sci fi": "Science Fiction",
    "scifi": "Science Fiction",
    "sf": "Science Fiction",
    "ya": "Young Adult",
    "teen": "Young Adult",
    "non-fiction": "Nonfiction",
    "non fiction": "Nonfiction",
    "lgbt": "LGBTQ+",
    "lgbtq": "LGBTQ+",
    "queer": "LGBTQ+",
    "gay": "LGBTQ+",
    "dystopian": "Dystopia",
    "classic": "Classics",
    "scary": "Horror",
    "spooky": "Horror",
    "funny": "Humor",
    "humour": "Humor",
    "kids": "Childrens",
    "children's": "Childrens",
    "self-help": "Self Help",
    "whodunit": "Mystery",
    "whodunnit": "Mystery",
    "detective": "Detective Fiction",
    "ww2": "World War II",
    "wwii": "World War II",
    "vampire": "Vampires",
    "witch": "Witches",
    "dragon": "Dragons",
    "fairy": "Fae",
    "faerie": "Fae",
    "myth": "Mythology",
    "myths": "Mythology",
    "romantic": "Romance",
    "greek myth": "Greek Mythology",
    "greek myths": "Greek Mythology",
    "greek gods": "Greek Mythology",
    "cosy mystery": "Cozy Mystery",
    "cozy": "Cozy Mystery",
    "heist": "Crime",
    "war": "War",
    "school": "Dark Academia",
    "academia": "Dark Academia",
    "love story": "Romance",
    "thrillers": "Thriller",
    "mysteries": "Mystery",
    "biographies": "Biography",
    "memoirs": "Memoir",
    "graphic novel": "Graphic Novels",
    "short story": "Short Stories",
    "poems": "Poetry",
    "historical": "Historical Fiction",
    "space": "Space Opera",
    "magical": "Magic",
    "retelling": "Retellings",
}
SHORT_WORDS = {"short", "shorter", "quick", "brief", "slim", "novella"}
LONG_WORDS = {"long", "longer", "epic-length", "doorstopper", "chunky", "thick"}
RECENT_WORDS = {"recent", "new", "newer", "modern", "latest"}
OLD_WORDS = {"old", "older", "vintage"}
FILLER = {
    "book",
    "books",
    "novel",
    "novels",
    "read",
    "reads",
    "something",
    "anything",
    "like",
    "similar",
    "recommend",
    "recommendation",
    "recommendations",
    "suggest",
    "want",
    "looking",
    "find",
    "give",
    "me",
    "but",
    "with",
    "and",
    "the",
    "that",
    "is",
    "are",
    "for",
    "to",
    "of",
    "in",
    "on",
    "an",
    "some",
    "any",
    "please",
    "can",
    "you",
    "would",
    "good",
    "best",
    "more",
    "than",
    "not",
    "too",
    "pages",
    "page",
    "under",
    "over",
    "less",
    "about",
    "i",
    "i'm",
    "im",
    "my",
    "it",
    "its",
    "this",
    "have",
    "has",
    "who",
    "what",
    "which",
    "one",
    "ones",
    "by",
    "a",
    "really",
    "very",
    "kind",
    "sort",
    "feel",
    "feels",
    "story",
    "stories",
    "set",
}
SHORT_PAGES, LONG_PAGES, RECENT_YEAR, OLD_YEAR = 320, 500, 2018, 1980


@dataclass
class ParsedQuery:
    text: str
    categories: list[str] = field(default_factory=list)
    like: list[str] = field(default_factory=list)  # ISBNs the reader wants "more like"
    like_label: str | None = None
    lookup: bool = False  # the request is just a title or series name
    author: str | None = None
    max_pages: int | None = None
    min_pages: int | None = None
    min_year: int | None = None
    max_year: int | None = None
    free_text: str = ""

    def describe(self) -> str:
        """One sentence saying how the request was understood."""
        bits = []
        if self.like_label:
            bits.append(("titled " if self.lookup else "similar to ") + self.like_label)
        if self.author:
            bits.append(f"by {self.author}")
        if self.categories:
            bits.append("filed under " + ", ".join(self.categories))
        if self.max_pages:
            bits.append(f"under {self.max_pages} pages")
        if self.min_pages:
            bits.append(f"over {self.min_pages} pages")
        if self.min_year:
            bits.append(f"published since {self.min_year}")
        if self.max_year:
            bits.append(f"published before {self.max_year}")
        if self.free_text:
            bits.append(f"matching “{self.free_text}”")
        return "; ".join(bits)


@dataclass
class Candidate:
    isbn: str
    score: float
    matched: list[str]


def _phrase_in(phrase: str, text: str) -> re.Match | None:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text)


def parse(query: str, content: ContentModel) -> ParsedQuery:
    parsed = ParsedQuery(text=query.strip())
    text = " " + re.sub(r"\s+", " ", query.lower()).strip() + " "
    consumed: list[str] = []

    # "like <title or series>" / "by <author>"
    def norm(s: str) -> str:
        return " ".join(tokens(s))

    normalised = " " + norm(query) + " "
    series_hit = max(
        (s for s in content.series_members if len(norm(s)) > 3 and _phrase_in(norm(s), normalised)),
        key=len,
        default=None,
    )
    title_hits = [
        d
        for d in content.docs
        if (len(tokens(d.title)) >= 2 or _phrase_in("like " + norm(d.title), normalised))
        and len(norm(d.title)) > 3
        and _phrase_in(norm(d.title), normalised)
    ]
    if title_hits:
        best = max(title_hits, key=lambda d: len(d.title))
        parsed.like, parsed.like_label = [best.isbn], best.title
        consumed.append(norm(best.title))
    elif series_hit:
        parsed.like = [content.isbns[i] for i in content.series_members[series_hit]]
        parsed.like_label = series_hit
        consumed.append(norm(series_hit))

    wants_similar = re.search(
        r"\b(like|similar|such as|fans? of|after|loved|liked|enjoyed|finished|more|reminds?)\b",
        text,
    )
    parsed.lookup = bool(parsed.like) and not wants_similar

    authors = {a for d in content.docs for a in d.authors}
    for author in sorted(authors, key=len, reverse=True):
        full, last = norm(author), norm(author).split(" ")[-1]
        if _phrase_in(full, normalised) or (len(last) > 3 and _phrase_in("by " + last, normalised)):
            parsed.author = author
            consumed += [full, last]
            break

    # genres, longest names first so "Fantasy Romance" wins over "Fantasy"
    names = {c.lower(): c for c in content.categories}
    names.update({k: v for k, v in CATEGORY_ALIASES.items() if v in content.category_index})
    for phrase in sorted(names, key=len, reverse=True):
        match = _phrase_in(phrase, text)
        if match:
            if names[phrase] not in parsed.categories:
                parsed.categories.append(names[phrase])
            text = text[: match.start()] + " " * len(phrase) + text[match.end() :]
            consumed.append(phrase)

    # length and era
    m = re.search(
        r"(?:under|less than|fewer than|below|max(?:imum)?)\s+(\d{2,4})\s*(?:pages|pp|p)\b", text
    )
    if m:
        parsed.max_pages = int(m.group(1))
    m = re.search(r"(?:over|more than|at least|above)\s+(\d{2,4})\s*(?:pages|pp|p)\b", text)
    if m:
        parsed.min_pages = int(m.group(1))
    words = set(tokens(text))
    if parsed.max_pages is None and words & SHORT_WORDS:
        parsed.max_pages = SHORT_PAGES
    if parsed.min_pages is None and words & LONG_WORDS:
        parsed.min_pages = LONG_PAGES
    m = re.search(r"(?:after|since|from)\s+((?:19|20)\d{2})", text)
    if m:
        parsed.min_year = int(m.group(1))
    elif words & RECENT_WORDS:
        parsed.min_year = RECENT_YEAR
    m = re.search(r"(?:before|pre-?)\s*((?:19|20)\d{2})", text)
    if m:
        parsed.max_year = int(m.group(1))
    elif words & OLD_WORDS:
        parsed.max_year = OLD_YEAR

    # whatever is left is matched against descriptions
    dropped = FILLER | SHORT_WORDS | LONG_WORDS | RECENT_WORDS | OLD_WORDS
    dropped |= {t for phrase in consumed for t in tokens(phrase)}
    rest = [t for t in tokens(text) if t not in dropped and not t.isdigit()]
    parsed.free_text = " ".join(rest)
    return parsed


def find_candidates(
    engine: RecommendationEngine,
    query: str,
    user_id: int | None = None,
    favourites: list[str] | None = None,
    limit: int = 24,
) -> tuple[ParsedQuery, list[Candidate]]:
    content = engine.content
    parsed = parse(query, content)
    n = len(content)
    score = np.zeros(n)
    matched: list[list[str]] = [[] for _ in range(n)]

    if parsed.free_text:
        text = content.text_scores(parsed.free_text)
        score += 1.0 * text
        for i in np.nonzero(text > 0.35)[0]:
            matched[i].append("description")

    if parsed.like:
        anchors = [content.index[i] for i in parsed.like]
        sim = content.similarity[:, anchors].mean(axis=1)
        sim = sim / sim.max() if sim.max() > 0 else sim
        score += 1.2 * sim
        for i in np.nonzero(sim > 0.45)[0]:
            matched[i].append(f"similar to {parsed.like_label}")
        if parsed.lookup:  # they typed the name: show the book itself first
            for i in anchors:
                score[i] += 3.0
                matched[i] = ["the book you named"]

    if parsed.categories:
        # Rare genres count for more: matching "Greek Mythology" beats matching "Fantasy".
        wanted = set(parsed.categories)
        weight = {c: content._category_idf[content.category_index[c]] for c in wanted}
        for i, doc in enumerate(content.docs):
            hit = wanted & set(doc.categories)
            if hit:
                score[i] += sum(weight[c] for c in hit) / sum(weight.values())
                matched[i].append(", ".join(sorted(hit)))

    if parsed.author:
        for i, doc in enumerate(content.docs):
            if parsed.author in doc.authors:
                score[i] += 1.5
                matched[i].append(f"by {parsed.author}")

    constrained = any([parsed.max_pages, parsed.min_pages, parsed.min_year, parsed.max_year])
    if score.max() <= 0 and constrained:
        score += 0.2 + engine._popularity  # "a short book" with nothing else to go on

    # A light personal tilt: among equally relevant books, prefer the reader's taste.
    if score.max() > 0:
        score += 0.15 * engine.personal_scores(user_id, favourites) * (score > 0)

    keep = np.ones(n, dtype=bool)
    for i, doc in enumerate(content.docs):
        pages, year = doc.pages or 0, doc.year or 0
        if parsed.max_pages and pages > parsed.max_pages:
            keep[i] = False
        if parsed.min_pages and pages < parsed.min_pages:
            keep[i] = False
        if parsed.min_year and year < parsed.min_year:
            keep[i] = False
        if parsed.max_year and year > parsed.max_year:
            keep[i] = False
    if not parsed.lookup:
        for isbn in parsed.like:  # do not answer "like Dune" with Dune
            keep[content.index[isbn]] = False
    score[~keep] = 0.0

    # Keep only books that are genuinely in the running, and at most three per
    # series so one saga cannot be the whole answer.
    floor = max(0.2, 0.4 * float(min(score.max(), 1.5)))
    order, per_series = [], {}
    for i in (int(i) for i in np.argsort(-score)):
        if score[i] < floor or len(order) == limit:
            break
        name = content.docs[i].series
        if name:
            if per_series.get(name, 0) >= 3 and not parsed.lookup:
                continue
            per_series[name] = per_series.get(name, 0) + 1
        order.append(i)
    for i in order:
        doc = content.docs[i]
        if parsed.max_pages or parsed.min_pages:
            matched[i].append(f"{doc.pages} pages")
        if parsed.min_year or parsed.max_year:
            matched[i].append(str(doc.year))
    return parsed, [Candidate(content.isbns[i], float(score[i]), matched[i]) for i in order]
