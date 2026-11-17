"""Load the catalogue and create believable demo readers.

A recommender has nothing to learn from an empty library, so on first start
we invent a few dozen fictional readers. Each has one or two "tastes" (a set
of genres they gravitate to) and rates, shelves and borrows books
accordingly. The result is reproducible: the same seed gives the same data.

All names here are made up. No real member data is included.
"""

from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    Author,
    Book,
    Category,
    Copy,
    Loan,
    Review,
    Series,
    ShelfEntry,
    ShelfStatus,
    User,
    utcnow,
)
from .security import hash_password

DEMO_USERNAME, DEMO_PASSWORD = "demo", "demo1234"

TASTES = {
    "romantasy": [
        "Romantasy",
        "Fantasy Romance",
        "Fae",
        "Enemies to Lovers",
        "Dragons",
        "New Adult",
    ],
    "ya_fantasy": ["Young Adult Fantasy", "Young Adult", "Magic", "Urban Fantasy", "Mythology"],
    "epic_fantasy": ["High Fantasy", "Epic Fantasy", "Fantasy", "Adventure", "Dragons"],
    "dystopia": ["Dystopia", "Science Fiction", "Young Adult"],
    "space": ["Science Fiction", "Space Opera", "Classics"],
    "thriller": ["Mystery Thriller", "Thriller", "Psychological Thriller", "Suspense", "Crime"],
    "whodunit": ["Mystery", "Detective Fiction", "Cozy Mystery", "Crime", "Classics"],
    "classics": ["Classics", "Literature", "Historical Fiction", "Literary Fiction"],
    "dark_romance": ["Dark Romance", "Dark", "Mafia Romance", "Contemporary Romance", "New Adult"],
    "contemporary": ["Contemporary", "Romance", "Mental Health", "LGBTQ+", "Coming Of Age"],
    "nonfiction": ["Nonfiction", "Self Help", "Psychology", "Memoir", "Personal Development"],
    "middle_grade": ["Middle Grade", "Childrens", "Greek Mythology", "Adventure"],
    "gothic": ["Horror", "Gothic", "Vampires", "Paranormal"],
}

FIRST_NAMES = (
    "Ada Ben Carla Dan Elif Finn Greta Hugo Ines Jonas Kira Leo Mara Nico Olga Pavel Quinn "
    "Rosa Sami Tess Ugo Vera Wim Xenia Yara Zoltan Alma Bruno Cleo Dario Edda Felix Gia Henrik "
    "Ilse Jurek Katka Luca Mina Noor Oskar Petra Rafa Selma Timo Una Viktor Wanda"
).split()
LAST_NAMES = (
    "Almasi Berg Costa Dvorak Eriksen Farkas Greco Horvat Ivanov Jansen Kovac Lindqvist Moreau "
    "Novak Olsen Petrov Quist Rossi Santos Toth Ulrich Varga Weiss Yilmaz Zeman"
).split()

REVIEW_LINES = {
    5: ["Could not put it down.", "Already want to reread it.", "An instant favourite.", ""],
    4: ["Really enjoyed this.", "Strong characters, great pacing.", "Would recommend.", ""],
    3: ["Fine, but it did not stay with me.", "Good in parts.", ""],
    2: ["Not for me.", "Struggled to finish it."],
    1: ["Gave up halfway."],
}

# The demo account: likes heist fantasy, a dystopia and a classic whodunit.
DEMO_HISTORY = [
    ("Six of Crows", 5),
    ("The Hunger Games", 5),
    ("Shadow and Bone", 4),
    ("Murder on the Orient Express", 4),
    ("Dune", 4),
    ("Twilight", 2),
]
DEMO_WANT = ["Circe", "The Song of Achilles"]
DEMO_FAVOURITES = ["Fantasy", "Mystery", "Dystopia"]


def load_catalogue(db: Session, path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    authors: dict[str, Author] = {}
    categories: dict[str, Category] = {}
    series: dict[str, Series] = {}
    rng = random.Random(7)
    for item in data["books"]:
        book = Book(
            isbn=item["isbn"],
            title=item["title"],
            publisher=item.get("publisher", ""),
            description=item.get("description", ""),
            year=item.get("year"),
            pages=item.get("pages"),
            cover_url=item.get("cover_url"),
        )
        if item.get("series"):
            book.series = series.setdefault(item["series"], Series(name=item["series"]))
        book.authors = [authors.setdefault(a, Author(name=a)) for a in item["authors"]]
        book.categories = [categories.setdefault(c, Category(name=c)) for c in item["categories"]]
        copies = item.get("copies") or [
            # The old database had no copies for some titles; give those two.
            {"condition": c, "shelf": f"{rng.randint(1, 9)}-{rng.randint(1, 9)}"}
            for c in ("New", "Good")
        ]
        book.copies = [Copy(condition=c["condition"], shelf=c["shelf"]) for c in copies]
        db.add(book)
    db.commit()
    return len(data["books"])


def seed_readers(db: Session, n_readers: int = 48, seed: int = 42) -> None:
    rng = random.Random(seed)
    books = db.scalars(select(Book)).all()
    genres = {b.isbn: {c.name for c in b.categories} for b in books}
    series_of = {b.isbn: b.series_id for b in books}
    copies = {b.isbn: [c.id for c in b.copies] for b in books}
    by_title = {b.title: b.isbn for b in books}
    category_id = {c.name: c.id for c in db.scalars(select(Category)).all()}
    now = utcnow()
    password = hash_password("not-a-real-login-" + str(seed))  # demo readers cannot log in
    on_loan: set[int] = set()

    def affinity(isbn: str, tastes: list[str]) -> float:
        best = 0.0
        for taste in tastes:
            wanted = TASTES[taste]
            hits = len(genres[isbn] & set(wanted))
            best = max(best, min(1.0, hits / 2.5))
        return best

    names = set()
    for n in range(n_readers):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in names:
                names.add(name)
                break
        tastes = rng.sample(list(TASTES), k=rng.choice([1, 2, 2]))
        favourites = [category_id[c] for t in tastes for c in TASTES[t][:2] if c in category_id]
        user = User(
            name=name,
            username=f"reader{n + 1:02d}",
            email=f"reader{n + 1:02d}@example.com",
            password_hash=password,
            favorite_category_ids=sorted(set(favourites)),
            is_demo=True,
            created_at=now - timedelta(days=rng.randint(60, 400)),
        )
        db.add(user)
        db.flush()

        # Readers mostly pick up books that match their taste, plus the odd wildcard.
        weights = [0.04 + affinity(b.isbn, tastes) ** 2 for b in books]
        picked: list[str] = []
        for isbn in rng.choices([b.isbn for b in books], weights=weights, k=rng.randint(10, 30)):
            if isbn not in picked:
                picked.append(isbn)
        # People who like book one of a series usually read on.
        for isbn in list(picked):
            if series_of[isbn] and rng.random() < 0.55:
                for other in books:
                    if (
                        other.series_id == series_of[isbn]
                        and other.isbn not in picked
                        and rng.random() < 0.6
                    ):
                        picked.append(other.isbn)

        for isbn in picked:
            when = now - timedelta(days=rng.randint(2, 300), hours=rng.randint(0, 23))
            roll = rng.random()
            if roll < 0.12:
                db.add(
                    ShelfEntry(user_id=user.id, isbn=isbn, status=ShelfStatus.want, updated_at=when)
                )
                continue
            if roll < 0.18:
                db.add(
                    ShelfEntry(
                        user_id=user.id, isbn=isbn, status=ShelfStatus.reading, updated_at=when
                    )
                )
                free = [c for c in copies[isbn] if c not in on_loan]
                if len(free) > 1:  # always leave one copy on the shelf for visitors
                    on_loan.add(free[0])
                    borrowed = now - timedelta(days=rng.randint(1, 18))
                    db.add(
                        Loan(
                            copy_id=free[0],
                            user_id=user.id,
                            borrowed_at=borrowed,
                            due_at=borrowed + timedelta(days=21),
                        )
                    )
                continue
            db.add(ShelfEntry(user_id=user.id, isbn=isbn, status=ShelfStatus.read, updated_at=when))
            if rng.random() < 0.5:
                db.add(
                    Loan(
                        copy_id=rng.choice(copies[isbn]),
                        user_id=user.id,
                        borrowed_at=when - timedelta(days=14),
                        due_at=when + timedelta(days=7),
                        returned_at=when,
                    )
                )
            if rng.random() < 0.8:
                raw = 2.3 + 2.4 * affinity(isbn, tastes) + rng.gauss(0, 0.7)
                rating = max(1, min(5, round(raw)))
                text = rng.choice(REVIEW_LINES[rating]) if rng.random() < 0.45 else ""
                db.add(
                    Review(
                        user_id=user.id,
                        isbn=isbn,
                        rating=rating,
                        text=text,
                        created_at=when,
                        updated_at=when,
                    )
                )

    demo = User(
        name="Demo Reader",
        username=DEMO_USERNAME,
        email="demo@example.com",
        password_hash=hash_password(DEMO_PASSWORD),
        favorite_category_ids=sorted(category_id[c] for c in DEMO_FAVOURITES if c in category_id),
    )
    db.add(demo)
    db.flush()
    for offset, (title, rating) in enumerate(DEMO_HISTORY):
        if title in by_title:
            when = now - timedelta(days=30 - offset)
            db.add(
                ShelfEntry(
                    user_id=demo.id, isbn=by_title[title], status=ShelfStatus.read, updated_at=when
                )
            )
            db.add(
                Review(
                    user_id=demo.id,
                    isbn=by_title[title],
                    rating=rating,
                    created_at=when,
                    updated_at=when,
                )
            )
    for title in DEMO_WANT:
        if title in by_title:
            db.add(ShelfEntry(user_id=demo.id, isbn=by_title[title], status=ShelfStatus.want))
    db.commit()


def seed_if_empty(db: Session) -> None:
    settings = get_settings()
    if db.scalar(select(Book.isbn).limit(1)) is None:
        load_catalogue(db, settings.catalogue_path)
        if settings.seed_demo_data:
            seed_readers(db)
