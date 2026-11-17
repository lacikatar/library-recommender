"""Everything a signed-in reader does: shelves, loans, waitlist, reviews, lists."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (
    Copy,
    Event,
    EventKind,
    Loan,
    ReadingList,
    ReadingListItem,
    Review,
    ShelfEntry,
    ShelfStatus,
    User,
    WaitlistEntry,
    utcnow,
)
from ..recsys import state
from ..security import current_user
from ..services import availability, book_cards, free_copy, get_book_or_404

router = APIRouter(prefix="/api", tags=["library"])


def my_state(db: Session, user: User, isbn: str) -> dict:
    """What this reader has done with this book."""
    shelf = db.get(ShelfEntry, (user.id, isbn))
    review = db.scalar(select(Review).where(Review.user_id == user.id, Review.isbn == isbn))
    loan = db.scalar(
        select(Loan)
        .join(Copy)
        .where(Loan.user_id == user.id, Copy.isbn == isbn, Loan.returned_at.is_(None))
    )
    waiting = db.scalar(
        select(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.isbn == isbn)
    )
    position = None
    if waiting:
        position = db.scalar(
            select(func.count())
            .select_from(WaitlistEntry)
            .where(WaitlistEntry.isbn == isbn, WaitlistEntry.joined_at <= waiting.joined_at)
        )
    list_ids = db.scalars(
        select(ReadingListItem.list_id)
        .join(ReadingList)
        .where(ReadingList.user_id == user.id, ReadingListItem.isbn == isbn)
    ).all()
    return {
        "shelf": shelf.status.value if shelf else None,
        "review": {"rating": review.rating, "text": review.text} if review else None,
        "loan": _loan_out(loan) if loan else None,
        "waitlist_position": position,
        "list_ids": list(list_ids),
    }


def _loan_out(loan: Loan) -> dict:
    return {
        "id": loan.id,
        "borrowed_at": loan.borrowed_at.isoformat(),
        "due_at": loan.due_at.isoformat(),
        "returned_at": loan.returned_at.isoformat() if loan.returned_at else None,
        "overdue": loan.returned_at is None and loan.due_at < utcnow(),
        "shelf": loan.copy.shelf,
        "condition": loan.copy.condition,
    }


def _set_shelf(db: Session, user_id: int, isbn: str, status: ShelfStatus) -> None:
    entry = db.get(ShelfEntry, (user_id, isbn))
    if entry:
        entry.status = status
    else:
        db.add(ShelfEntry(user_id=user_id, isbn=isbn, status=status))


# ------------------------------------------------------------------ shelves
class ShelfIn(BaseModel):
    status: ShelfStatus | None


@router.put("/books/{isbn}/shelf")
def set_shelf(
    isbn: str, body: ShelfIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    get_book_or_404(db, isbn)
    if body.status is None:
        db.execute(delete(ShelfEntry).where(ShelfEntry.user_id == user.id, ShelfEntry.isbn == isbn))
    else:
        _set_shelf(db, user.id, isbn, body.status)
    db.commit()
    state.mark_changed()
    return my_state(db, user, isbn)


@router.post("/books/{isbn}/dismiss", status_code=204)
def not_interested(isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_book_or_404(db, isbn)
    db.add(Event(user_id=user.id, isbn=isbn, kind=EventKind.dismiss))
    db.commit()
    state.mark_changed()


@router.delete("/books/{isbn}/dismiss", status_code=204)
def undo_not_interested(
    isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    db.execute(
        delete(Event).where(
            Event.user_id == user.id, Event.isbn == isbn, Event.kind == EventKind.dismiss
        )
    )
    db.commit()
    state.mark_changed()


# ------------------------------------------------------------------ reviews
class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field("", max_length=4000)


@router.put("/books/{isbn}/review")
def save_review(
    isbn: str, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    get_book_or_404(db, isbn)
    review = db.scalar(select(Review).where(Review.user_id == user.id, Review.isbn == isbn))
    if review:
        review.rating, review.text = body.rating, body.text.strip()
    else:
        db.add(Review(user_id=user.id, isbn=isbn, rating=body.rating, text=body.text.strip()))
    # Rating a book means you have read it.
    _set_shelf(db, user.id, isbn, ShelfStatus.read)
    db.commit()
    state.mark_changed()
    return my_state(db, user, isbn)


@router.delete("/books/{isbn}/review")
def delete_review(isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(Review).where(Review.user_id == user.id, Review.isbn == isbn))
    db.commit()
    state.mark_changed()
    return my_state(db, user, isbn)


# -------------------------------------------------------------------- loans
@router.post("/books/{isbn}/borrow", status_code=201)
def borrow(isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    get_book_or_404(db, isbn)
    active = db.scalars(
        select(Loan).where(Loan.user_id == user.id, Loan.returned_at.is_(None))
    ).all()
    if any(loan.copy.isbn == isbn for loan in active):
        raise HTTPException(409, "You already have this book out.")
    if len(active) >= settings.max_active_loans:
        raise HTTPException(
            409, f"You have {settings.max_active_loans} books out. Return one to borrow another."
        )
    copy = free_copy(db, isbn)
    if copy is None:
        raise HTTPException(409, "Every copy is out. Join the waitlist instead.")

    # Waitlist is first come, first served: only people at the front may take free copies.
    queue = db.scalars(
        select(WaitlistEntry.user_id)
        .where(WaitlistEntry.isbn == isbn)
        .order_by(WaitlistEntry.joined_at)
    ).all()
    free_now = availability(db, [isbn])[isbn][0]
    if queue and user.id not in queue[:free_now]:
        raise HTTPException(409, "Readers on the waitlist are ahead of you for this copy.")

    now = utcnow()
    db.add(
        Loan(
            copy_id=copy.id,
            user_id=user.id,
            borrowed_at=now,
            due_at=now + timedelta(days=settings.loan_days),
        )
    )
    db.execute(
        delete(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.isbn == isbn)
    )
    shelf = db.get(ShelfEntry, (user.id, isbn))
    if shelf is None or shelf.status == ShelfStatus.want:
        _set_shelf(db, user.id, isbn, ShelfStatus.reading)
    db.commit()
    state.mark_changed()
    return my_state(db, user, isbn)


@router.post("/loans/{loan_id}/return")
def return_loan(loan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    loan = db.get(Loan, loan_id)
    if loan is None or loan.user_id != user.id:
        raise HTTPException(404, "No such loan.")
    if loan.returned_at is None:
        loan.returned_at = utcnow()
        isbn = loan.copy.isbn
        shelf = db.get(ShelfEntry, (user.id, isbn))
        if shelf and shelf.status == ShelfStatus.reading:
            shelf.status = ShelfStatus.read
        db.commit()
        state.mark_changed()
    return _loan_out(loan)


@router.post("/books/{isbn}/waitlist", status_code=201)
def join_waitlist(isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_book_or_404(db, isbn)
    if free_copy(db, isbn) is not None and not db.scalar(
        select(func.count()).select_from(WaitlistEntry).where(WaitlistEntry.isbn == isbn)
    ):
        raise HTTPException(409, "A copy is on the shelf. You can borrow it now.")
    exists = db.scalar(
        select(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.isbn == isbn)
    )
    if not exists:
        db.add(WaitlistEntry(user_id=user.id, isbn=isbn))
        db.commit()
    return my_state(db, user, isbn)


@router.delete("/books/{isbn}/waitlist")
def leave_waitlist(isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(
        delete(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.isbn == isbn)
    )
    db.commit()
    return my_state(db, user, isbn)


# --------------------------------------------------------------- my library
@router.get("/me/library")
def my_library(user: User = Depends(current_user), db: Session = Depends(get_db)):
    loans = db.scalars(
        select(Loan).where(Loan.user_id == user.id).order_by(Loan.borrowed_at.desc())
    ).all()
    loan_cards = {c["isbn"]: c for c in book_cards(db, list({l.copy.isbn for l in loans}))}

    def loans_out(items):
        return [{**_loan_out(l), "book": loan_cards[l.copy.isbn]} for l in items]

    shelves = {status.value: [] for status in ShelfStatus}
    entries = db.scalars(
        select(ShelfEntry)
        .where(ShelfEntry.user_id == user.id)
        .order_by(ShelfEntry.updated_at.desc())
    ).all()
    cards = {c["isbn"]: c for c in book_cards(db, [e.isbn for e in entries])}
    ratings = dict(
        db.execute(select(Review.isbn, Review.rating).where(Review.user_id == user.id)).all()
    )
    for e in entries:
        shelves[e.status.value].append({**cards[e.isbn], "my_rating": ratings.get(e.isbn)})

    waiting = db.scalars(
        select(WaitlistEntry)
        .where(WaitlistEntry.user_id == user.id)
        .order_by(WaitlistEntry.joined_at)
    ).all()
    wait_cards = {c["isbn"]: c for c in book_cards(db, [w.isbn for w in waiting])}
    waitlist = []
    for w in waiting:
        position = db.scalar(
            select(func.count())
            .select_from(WaitlistEntry)
            .where(WaitlistEntry.isbn == w.isbn, WaitlistEntry.joined_at <= w.joined_at)
        )
        book = wait_cards[w.isbn]
        waitlist.append(
            {"book": book, "position": position, "ready": book["available_copies"] >= position}
        )

    return {
        "current_loans": loans_out([l for l in loans if l.returned_at is None]),
        "past_loans": loans_out([l for l in loans if l.returned_at is not None][:30]),
        "shelves": shelves,
        "waitlist": waitlist,
        "loan_limit": get_settings().max_active_loans,
    }


# ------------------------------------------------------------ reading lists
class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1000)


def _own_list(db: Session, user: User, list_id: int) -> ReadingList:
    reading_list = db.get(ReadingList, list_id)
    if reading_list is None or reading_list.user_id != user.id:
        raise HTTPException(404, "No such reading list.")
    return reading_list


def _list_out(db: Session, reading_list: ReadingList, with_books: bool) -> dict:
    isbns = [item.isbn for item in reading_list.items]
    cards = book_cards(db, isbns if with_books else isbns[:4])
    out = {
        "id": reading_list.id,
        "name": reading_list.name,
        "description": reading_list.description,
        "book_count": len(isbns),
        "covers": [c["cover_url"] for c in cards[:4]],
    }
    if with_books:
        out["books"] = cards
    return out


@router.get("/lists")
def my_lists(user: User = Depends(current_user), db: Session = Depends(get_db)):
    lists = db.scalars(
        select(ReadingList).where(ReadingList.user_id == user.id).order_by(ReadingList.created_at)
    ).all()
    return [_list_out(db, l, with_books=False) for l in lists]


@router.post("/lists", status_code=201)
def create_list(body: ListIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    reading_list = ReadingList(
        user_id=user.id, name=body.name.strip(), description=body.description.strip()
    )
    db.add(reading_list)
    db.commit()
    return _list_out(db, reading_list, with_books=True)


@router.get("/lists/{list_id}")
def get_list(list_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _list_out(db, _own_list(db, user, list_id), with_books=True)


@router.patch("/lists/{list_id}")
def rename_list(
    list_id: int, body: ListIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    reading_list = _own_list(db, user, list_id)
    reading_list.name, reading_list.description = body.name.strip(), body.description.strip()
    db.commit()
    return _list_out(db, reading_list, with_books=True)


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(list_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_list(db, user, list_id))
    db.commit()


@router.put("/lists/{list_id}/books/{isbn}", status_code=204)
def add_to_list(
    list_id: int, isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    _own_list(db, user, list_id)
    get_book_or_404(db, isbn)
    if db.get(ReadingListItem, (list_id, isbn)) is None:
        db.add(ReadingListItem(list_id=list_id, isbn=isbn))
        db.commit()


@router.delete("/lists/{list_id}/books/{isbn}", status_code=204)
def remove_from_list(
    list_id: int, isbn: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    _own_list(db, user, list_id)
    db.execute(
        delete(ReadingListItem).where(
            ReadingListItem.list_id == list_id, ReadingListItem.isbn == isbn
        )
    )
    db.commit()
