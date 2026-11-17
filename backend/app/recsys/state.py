"""Wires the engine to the database.

The engine lives in memory for the life of the process. Routers call
`mark_changed()` after any write that affects recommendations; the next read
reloads reader behaviour (a handful of small queries) before ranking.
"""

from __future__ import annotations

import itertools
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Book, Copy, Event, EventKind, Loan, Review, ShelfEntry
from .content import BookDoc
from .engine import RecommendationEngine, Signal

_engine: RecommendationEngine | None = None
_version = itertools.count(1)
_current_version = 0
_catalogue_signature = None


def mark_changed() -> None:
    global _current_version
    _current_version = next(_version)


def reset() -> None:
    """Forget the cached engine (catalogue changed, or a test swapped the DB)."""
    global _engine
    _engine = None
    mark_changed()


def load_docs(db: Session) -> list[BookDoc]:
    books = db.scalars(
        select(Book)
        .options(
            selectinload(Book.authors), selectinload(Book.categories), selectinload(Book.series)
        )
        .order_by(Book.isbn)
    ).all()
    return [
        BookDoc(
            isbn=b.isbn,
            title=b.title,
            authors=[a.name for a in b.authors],
            series=b.series.name if b.series else None,
            categories=[c.name for c in b.categories],
            description=b.description or "",
            year=b.year,
            pages=b.pages,
        )
        for b in books
    ]


def load_interactions(db: Session) -> dict[int, dict[str, Signal]]:
    by_user: dict[int, dict[str, Signal]] = defaultdict(lambda: defaultdict(Signal))
    for r in db.execute(select(Review.user_id, Review.isbn, Review.rating, Review.updated_at)):
        signal = by_user[r.user_id][r.isbn]
        signal.rating = r.rating
        signal.touch(r.updated_at)
    for s in db.execute(
        select(ShelfEntry.user_id, ShelfEntry.isbn, ShelfEntry.status, ShelfEntry.updated_at)
    ):
        signal = by_user[s.user_id][s.isbn]
        signal.shelf = s.status.value
        signal.touch(s.updated_at)
    for l in db.execute(select(Loan.user_id, Copy.isbn, Loan.borrowed_at).join(Copy)):
        signal = by_user[l.user_id][l.isbn]
        signal.borrowed = True
        signal.touch(l.borrowed_at)
    for e in db.execute(select(Event.user_id, Event.isbn, Event.kind, Event.created_at)):
        signal = by_user[e.user_id][e.isbn]
        if e.kind == EventKind.dismiss:
            signal.dismissed = True
        else:
            signal.views += 1
    return {u: dict(books) for u, books in by_user.items()}


def get_engine(db: Session) -> RecommendationEngine:
    global _engine, _catalogue_signature
    # Books can be added by another process (the sync command), so check a cheap
    # fingerprint of the catalogue on every request and rebuild when it changes.
    signature = tuple(db.execute(select(func.count(Book.isbn), func.max(Book.added_at))).one())
    if _engine is None or signature != _catalogue_signature:
        _engine = RecommendationEngine(load_docs(db))
        _catalogue_signature = signature
        mark_changed()
    _engine.refresh(_current_version, lambda: load_interactions(db))
    return _engine
