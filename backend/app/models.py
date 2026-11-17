from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


book_authors = Table(
    "book_authors",
    Base.metadata,
    Column("isbn", ForeignKey("books.isbn", ondelete="CASCADE"), primary_key=True),
    Column("author_id", ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True),
)

book_categories = Table(
    "book_categories",
    Base.metadata,
    Column("isbn", ForeignKey("books.isbn", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)


class Author(Base):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    books: Mapped[list[Book]] = relationship(secondary=book_authors, back_populates="authors")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    books: Mapped[list[Book]] = relationship(secondary=book_categories, back_populates="categories")


class Series(Base):
    __tablename__ = "series"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    books: Mapped[list[Book]] = relationship(back_populates="series")


class Book(Base):
    __tablename__ = "books"
    isbn: Mapped[str] = mapped_column(String(13), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    publisher: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None]
    pages: Mapped[int | None]
    cover_url: Mapped[str | None] = mapped_column(String(500))
    # Set for books added by the catalogue sync; None for the original collection.
    added_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id", ondelete="SET NULL"))

    series: Mapped[Series | None] = relationship(back_populates="books")
    authors: Mapped[list[Author]] = relationship(secondary=book_authors, back_populates="books")
    categories: Mapped[list[Category]] = relationship(
        secondary=book_categories, back_populates="books"
    )
    copies: Mapped[list[Copy]] = relationship(back_populates="book", cascade="all, delete-orphan")


class Copy(Base):
    __tablename__ = "copies"
    id: Mapped[int] = mapped_column(primary_key=True)
    isbn: Mapped[str] = mapped_column(ForeignKey("books.isbn", ondelete="CASCADE"), index=True)
    condition: Mapped[str] = mapped_column(String(20), default="Good")
    shelf: Mapped[str] = mapped_column(String(20), default="")
    book: Mapped[Book] = relationship(back_populates="copies")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    favorite_category_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    copy_id: Mapped[int] = mapped_column(ForeignKey("copies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    borrowed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime)
    copy: Mapped[Copy] = relationship()


class WaitlistEntry(Base):
    __tablename__ = "waitlist"
    __table_args__ = (UniqueConstraint("user_id", "isbn"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    isbn: Mapped[str] = mapped_column(ForeignKey("books.isbn", ondelete="CASCADE"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "isbn"),
        CheckConstraint("rating BETWEEN 1 AND 5"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    isbn: Mapped[str] = mapped_column(ForeignKey("books.isbn", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship()


class ShelfStatus(str, enum.Enum):
    want = "want"
    reading = "reading"
    read = "read"


class ShelfEntry(Base):
    """Where a book sits on a reader's personal shelf: want / reading / read."""

    __tablename__ = "shelf_entries"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    isbn: Mapped[str] = mapped_column(
        ForeignKey("books.isbn", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ShelfStatus] = mapped_column(Enum(ShelfStatus))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ReadingList(Base):
    __tablename__ = "reading_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    items: Mapped[list[ReadingListItem]] = relationship(
        back_populates="reading_list",
        cascade="all, delete-orphan",
        order_by="ReadingListItem.added_at",
    )


class ReadingListItem(Base):
    __tablename__ = "reading_list_items"
    list_id: Mapped[int] = mapped_column(
        ForeignKey("reading_lists.id", ondelete="CASCADE"), primary_key=True
    )
    isbn: Mapped[str] = mapped_column(
        ForeignKey("books.isbn", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reading_list: Mapped[ReadingList] = relationship(back_populates="items")


class EventKind(str, enum.Enum):
    view = "view"
    dismiss = "dismiss"  # "not interested"


class Event(Base):
    """Lightweight behaviour log that feeds the recommender."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_isbn", "user_id", "isbn"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    isbn: Mapped[str] = mapped_column(ForeignKey("books.isbn", ondelete="CASCADE"))
    kind: Mapped[EventKind] = mapped_column(Enum(EventKind))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncRun(Base):
    """One run of the catalogue sync, so the schedule survives restarts."""

    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | schedule
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
