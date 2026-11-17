from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Book, Category, User
from ..recsys import assistant, state
from ..security import optional_user
from ..services import book_cards

router = APIRouter(prefix="/api", tags=["recommendations"])

# Shown to visitors who are not signed in.
SHOWCASE_GENRES = ["Fantasy", "Mystery", "Classics", "Science Fiction", "Romance"]


def favourite_names(db: Session, user: User | None) -> list[str]:
    if not user or not user.favorite_category_ids:
        return []
    return list(
        db.scalars(select(Category.name).where(Category.id.in_(user.favorite_category_ids))).all()
    )


def _with_reasons(db: Session, recs) -> list[dict]:
    cards = {c["isbn"]: c for c in book_cards(db, [r.isbn for r in recs])}
    return [
        {
            **cards[r.isbn],
            "reason": r.reason,
            "reason_kind": r.kind,
            "because_isbn": r.because_isbn,
            "signals": r.signals,
        }
        for r in recs
        if r.isbn in cards
    ]


@router.get("/recommendations")
def recommendations(
    limit: int = Query(24, ge=1, le=48),
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
):
    engine = state.get_engine(db)
    recs = engine.recommend(user.id if user else None, favourite_names(db, user), limit=limit)
    history = engine.history(user.id) if user else {}
    return {
        "items": _with_reasons(db, recs),
        "known_books": sum(1 for s in history.values() if s.strength > 0),
    }


@router.get("/recommendations/home")
def home(user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    """The shelves on the home page."""
    engine = state.get_engine(db)
    shelves: list[dict] = []
    shown: set[str] = set()

    def add(title: str, items: list[dict], kind: str, subtitle: str = "") -> None:
        if len(items) >= 4:
            shelves.append({"title": title, "subtitle": subtitle, "kind": kind, "books": items})
            shown.update(i["isbn"] for i in items)

    def new_arrivals(exclude: set[str]) -> None:
        recent = db.scalars(
            select(Book.isbn)
            .where(Book.added_at.is_not(None))
            .order_by(Book.added_at.desc())
            .limit(30)
        ).all()
        isbns = [i for i in recent if i not in exclude][:12]
        add("New on the shelves", book_cards(db, isbns), "new")

    if user:
        favourites = favourite_names(db, user)
        seen = engine.consumed(user.id)
        add(
            f"Picked for {user.name.split()[0]}",
            _with_reasons(db, engine.recommend(user.id, favourites, limit=12)),
            "for_you",
        )
        rows = 0
        for anchor in engine.favourite_anchors(user.id, limit=5):
            similar = engine.similar(
                anchor, limit=10, exclude=seen | shown, same_series=False, min_score=0.15
            )
            if len(similar) >= 4 and rows < 2:
                rows += 1
                add(
                    f"Because you enjoyed {engine.docs[anchor].title}",
                    book_cards(db, similar),
                    "because",
                )
        new_arrivals(seen | shown)
        add(
            "Popular with other readers",
            book_cards(db, engine.popular(limit=10, exclude=seen | shown, one_per_series=True)),
            "popular",
        )
    else:
        add(
            "Popular with readers",
            book_cards(db, engine.popular(limit=12, one_per_series=True)),
            "popular",
        )
        new_arrivals(shown)
        by_genre = {name: [] for name in SHOWCASE_GENRES}
        for isbn in engine.popular(limit=len(engine.content), one_per_series=True):
            for name in SHOWCASE_GENRES:
                if (
                    name in engine.docs[isbn].categories
                    and len(by_genre[name]) < 10
                    and isbn not in shown
                ):
                    by_genre[name].append(isbn)
                    shown.add(isbn)
                    break
        for name, isbns in by_genre.items():
            add(name, book_cards(db, isbns), "genre")
    return {"shelves": shelves}


class AskIn(BaseModel):
    message: str = Field(min_length=2, max_length=600)


@router.get("/assistant/status")
def assistant_status():
    settings = get_settings()
    return {"llm": settings.llm_enabled}


@router.post("/assistant/ask")
def ask(body: AskIn, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    engine = state.get_engine(db)
    answer = assistant.ask(
        engine,
        get_settings(),
        body.message,
        user_id=user.id if user else None,
        favourites=favourite_names(db, user),
    )
    cards = {c["isbn"]: c for c in book_cards(db, [p.isbn for p in answer.picks])}
    return {
        "reply": answer.reply,
        "mode": answer.mode,
        "understood": answer.understood,
        "picks": [{**cards[p.isbn], "reason": p.reason} for p in answer.picks if p.isbn in cards],
    }
