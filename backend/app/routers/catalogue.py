from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Author,
    Book,
    Category,
    Event,
    EventKind,
    Review,
    Series,
    SyncRun,
    User,
    WaitlistEntry,
    book_authors,
    book_categories,
)
from ..recsys import state
from ..security import optional_user
from ..services import availability, book_cards, get_book_or_404, rating_stats

router = APIRouter(prefix="/api", tags=["catalogue"])

Sort = Literal["relevance", "title", "newest", "rating", "popular", "added"]


@router.get("/books")
def list_books(
    q: str = Query("", max_length=200),
    category: str | None = None,
    author_id: int | None = None,
    series_id: int | None = None,
    available: bool = False,
    sort: Sort = "relevance",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=60),
    db: Session = Depends(get_db),
):
    query = select(Book.isbn, Book.title, Book.year, Book.added_at)
    if category:
        query = query.join(book_categories).join(Category).where(Category.name == category)
    if author_id:
        query = query.join(book_authors).where(book_authors.c.author_id == author_id)
    if series_id:
        query = query.where(Book.series_id == series_id)
    rows = db.execute(query).all()
    isbns = [r.isbn for r in rows]

    if available:
        stock = availability(db)
        isbns = [i for i in isbns if stock.get(i, (0, 0))[0] > 0]

    engine = state.get_engine(db)
    if q.strip():
        scores = engine.content.text_scores(q)
        relevance = {i: scores[engine.content.index[i]] for i in isbns if i in engine.content.index}
        isbns = [i for i in isbns if relevance.get(i, 0) >= 0.15]
    else:
        relevance = {}

    title = {r.isbn: r.title.lower() for r in rows}
    year = {r.isbn: r.year or 0 for r in rows}
    if sort == "relevance" and relevance:
        isbns.sort(key=lambda i: -relevance[i])
    elif sort == "newest":
        isbns.sort(key=lambda i: (-year[i], title[i]))
    elif sort == "rating":
        stats = rating_stats(db)
        isbns.sort(key=lambda i: (-stats.get(i, (0, 0))[0], -stats.get(i, (0, 0))[1], title[i]))
    elif sort == "added":
        added = {r.isbn: r.added_at for r in rows if r.added_at}
        isbns = sorted(isbns, key=lambda i: title[i])
        isbns.sort(key=lambda i: added.get(i) or datetime.min, reverse=True)
    elif sort == "popular":
        rank = {isbn: n for n, isbn in enumerate(engine.popular(limit=len(engine.content)))}
        isbns.sort(key=lambda i: rank.get(i, 1e9))
    else:
        isbns.sort(key=lambda i: title[i])

    start = (page - 1) * page_size
    return {
        "total": len(isbns),
        "page": page,
        "page_size": page_size,
        "items": book_cards(db, isbns[start : start + page_size]),
    }


@router.get("/books/{isbn}")
def book_detail(
    isbn: str, user: User | None = Depends(optional_user), db: Session = Depends(get_db)
):
    book = get_book_or_404(db, isbn)
    detail = book_cards(db, [isbn])[0]
    detail.update(description=book.description, publisher=book.publisher)
    detail["waitlist_length"] = db.scalar(
        select(func.count()).select_from(WaitlistEntry).where(WaitlistEntry.isbn == isbn)
    )
    if book.series:
        siblings = db.scalars(
            select(Book.isbn)
            .where(Book.series_id == book.series_id)
            .order_by(Book.year, Book.title)
        ).all()
        detail["series_books"] = book_cards(db, list(siblings))

    mine = None
    if user:
        from .library import my_state  # local import avoids a circular import

        mine = my_state(db, user, isbn)
        db.add(Event(user_id=user.id, isbn=isbn, kind=EventKind.view))
        db.commit()
        state.mark_changed()
    detail["mine"] = mine
    return detail


@router.get("/books/{isbn}/similar")
def similar_books(
    isbn: str,
    limit: int = Query(8, ge=1, le=20),
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
):
    get_book_or_404(db, isbn)
    engine = state.get_engine(db)
    return book_cards(db, engine.similar(isbn, limit=limit))


@router.get("/books/{isbn}/reviews")
def book_reviews(isbn: str, db: Session = Depends(get_db)):
    get_book_or_404(db, isbn)
    reviews = db.scalars(
        select(Review).where(Review.isbn == isbn).order_by(Review.updated_at.desc()).limit(50)
    ).all()
    histogram = dict(
        db.execute(
            select(Review.rating, func.count()).where(Review.isbn == isbn).group_by(Review.rating)
        ).all()
    )
    return {
        "histogram": {str(star): histogram.get(star, 0) for star in range(5, 0, -1)},
        "items": [
            {
                "id": r.id,
                "reader": r.user.name,
                "rating": r.rating,
                "text": r.text,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in reviews
        ],
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Category.id, Category.name, func.count(book_categories.c.isbn))
        .join(book_categories)
        .group_by(Category.id)
        .order_by(Category.name)
    ).all()
    return [{"id": i, "name": name, "book_count": n} for i, name, n in rows]


@router.get("/authors")
def list_authors(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Author.id, Author.name, func.count(book_authors.c.isbn))
        .join(book_authors)
        .group_by(Author.id)
    ).all()
    authors = [{"id": i, "name": name, "book_count": n} for i, name, n in rows]
    # Sort by surname, the way a library shelves them.
    authors.sort(key=lambda a: (a["name"].split()[-1].lower(), a["name"].lower()))
    return authors


@router.get("/authors/{author_id}")
def author_detail(author_id: int, db: Session = Depends(get_db)):
    author = db.get(Author, author_id)
    if author is None:
        raise HTTPException(404, "No such author.")
    isbns = db.scalars(
        select(Book.isbn)
        .join(book_authors)
        .where(book_authors.c.author_id == author_id)
        .order_by(Book.year, Book.title)
    ).all()
    return {"id": author.id, "name": author.name, "books": book_cards(db, list(isbns))}


@router.get("/series")
def list_series(db: Session = Depends(get_db)):
    all_series = db.scalars(select(Series).order_by(Series.name)).all()
    out = []
    for s in all_series:
        isbns = db.scalars(
            select(Book.isbn).where(Book.series_id == s.id).order_by(Book.year, Book.title)
        ).all()
        if isbns:
            cards = book_cards(db, list(isbns))
            out.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "book_count": len(cards),
                    "authors": sorted({a["name"] for c in cards for a in c["authors"]}),
                    "covers": [c["cover_url"] for c in cards[:4]],
                }
            )
    return out


@router.get("/series/{series_id}")
def series_detail(series_id: int, db: Session = Depends(get_db)):
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(404, "No such series.")
    isbns = db.scalars(
        select(Book.isbn).where(Book.series_id == series_id).order_by(Book.year, Book.title)
    ).all()
    return {"id": series.id, "name": series.name, "books": book_cards(db, list(isbns))}


@router.get("/catalogue/updates")
def catalogue_updates(db: Session = Depends(get_db)):
    """When the catalogue sync last ran and what it added."""
    from ..config import get_settings

    last = db.scalar(
        select(SyncRun)
        .where(SyncRun.finished_at.is_not(None))
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    )
    return {
        "schedule_hours": get_settings().sync_interval_hours or None,
        "books_added_total": db.scalar(
            select(func.count()).select_from(Book).where(Book.added_at.is_not(None))
        ),
        "last_run": None
        if last is None
        else {
            "finished_at": last.finished_at.isoformat(),
            "trigger": last.trigger,
            "added": last.added,
            "ok": not last.error,
        },
    }
