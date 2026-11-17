"""Shared read helpers: turning ISBNs into the JSON the frontend shows."""

from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import Book, Copy, Loan, Review

CONDITION_ORDER = {"New": 0, "Good": 1, "Fair": 2}


def get_book_or_404(db: Session, isbn: str) -> Book:
    book = db.get(Book, isbn)
    if book is None:
        raise HTTPException(404, "That book is not in the catalogue.")
    return book


def availability(db: Session, isbns: list[str] | None = None) -> dict[str, tuple[int, int]]:
    """isbn -> (copies on the shelf right now, copies owned)."""
    total_q = select(Copy.isbn, func.count()).group_by(Copy.isbn)
    out_q = (
        select(Copy.isbn, func.count())
        .join(Loan, Loan.copy_id == Copy.id)
        .where(Loan.returned_at.is_(None))
        .group_by(Copy.isbn)
    )
    if isbns is not None:
        total_q = total_q.where(Copy.isbn.in_(isbns))
        out_q = out_q.where(Copy.isbn.in_(isbns))
    out = dict(db.execute(out_q).all())
    return {isbn: (total - out.get(isbn, 0), total) for isbn, total in db.execute(total_q)}


def rating_stats(db: Session, isbns: list[str] | None = None) -> dict[str, tuple[float, int]]:
    q = select(Review.isbn, func.avg(Review.rating), func.count()).group_by(Review.isbn)
    if isbns is not None:
        q = q.where(Review.isbn.in_(isbns))
    return {isbn: (round(float(avg), 2), n) for isbn, avg, n in db.execute(q)}


def book_cards(db: Session, isbns: list[str]) -> list[dict]:
    """Compact book summaries, in the order the ISBNs were given."""
    if not isbns:
        return []
    books = db.scalars(
        select(Book)
        .where(Book.isbn.in_(isbns))
        .options(
            selectinload(Book.authors), selectinload(Book.categories), selectinload(Book.series)
        )
    ).all()
    by_isbn = {b.isbn: b for b in books}
    stock, ratings = availability(db, isbns), rating_stats(db, isbns)
    return [card(by_isbn[i], stock, ratings) for i in isbns if i in by_isbn]


def card(book: Book, stock: dict, ratings: dict) -> dict:
    available, total = stock.get(book.isbn, (0, 0))
    avg, count = ratings.get(book.isbn, (None, 0))
    return {
        "isbn": book.isbn,
        "title": book.title,
        "authors": [{"id": a.id, "name": a.name} for a in book.authors],
        "series": {"id": book.series.id, "name": book.series.name} if book.series else None,
        "cover_url": book.cover_url,
        "year": book.year,
        "pages": book.pages,
        "categories": sorted(c.name for c in book.categories),
        "rating_avg": avg,
        "rating_count": count,
        "available_copies": available,
        "total_copies": total,
    }


def free_copy(db: Session, isbn: str) -> Copy | None:
    """The best-condition copy that is not out on loan."""
    on_loan = select(Loan.copy_id).where(Loan.returned_at.is_(None))
    copies = db.scalars(select(Copy).where(Copy.isbn == isbn, Copy.id.not_in(on_loan))).all()
    return min(copies, key=lambda c: (CONDITION_ORDER.get(c.condition, 9), c.id), default=None)


def group_by(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped
