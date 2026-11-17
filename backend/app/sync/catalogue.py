"""Add new books to the catalogue from Open Library, with Google Books as backup.

For each subject (fantasy, mystery, ...) the sync asks Open Library for the
most-read English books first published in the last few years, skips any the
library already has, and fills in each new one: authors, year, genres,
description, cover, page count and an English print edition's ISBN. A book
goes on the shelf only if it has a real description, a cover and at least one
genre, because a book without those cannot be recommended well.

Each run is recorded in `sync_runs`. New books get two copies and an
`added_at` date, which feeds the "New on the shelves" row on the home page.
"""

from __future__ import annotations

import logging
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import Author, Book, Category, Copy, Series, SyncRun, utcnow
from ..recsys import state
from . import sources
from .genres import map_subjects
from .sources import Http, SourceError

log = logging.getLogger(__name__)

MIN_DESCRIPTION = 150  # characters
MIN_READERS = 10  # Open Library reading-log entries; filters out obscure records
COPIES_PER_BOOK = 2
SCAN_FACTOR = 6  # look at up to per_subject * SCAN_FACTOR candidates per subject
JUNK_TITLE = re.compile(
    r"\b(summary|study guide|workbook|sparknotes|cliffsnotes|box(?:ed)? ?set|omnibus|"
    r"collection|complete series|books? \d+\s*[-–&]\s*\d+|colou?ring|journal|"
    r"special edition|deluxe edition|untitled)\b",
    re.I,
)


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    stopped: bool = False

    def summary(self) -> str:
        parts = [f"added {len(self.added)}"]
        if self.skipped:
            parts.append(
                "skipped " + ", ".join(f"{n} {why}" for why, n in self.skipped.most_common())
            )
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return "; ".join(parts)


@dataclass
class NewBook:
    isbn: str
    title: str
    authors: list[str]
    year: int | None
    pages: int | None
    publisher: str
    description: str
    cover_url: str
    categories: list[str]
    series: str | None = None


def normalise_title(title: str) -> str:
    title = title.lower().split(":")[0]
    title = re.sub(r"^(the|a|an) ", "", title.strip())
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def normalise_name(name: str) -> str:
    return re.sub(r"[^a-z]+", "", name.lower())


class CatalogueSync:
    def __init__(
        self,
        db: Session,
        http: Http,
        settings: Settings,
        should_stop: Callable[[], bool] = lambda: False,
    ):
        self.db = db
        self.http = http
        self.settings = settings
        self.should_stop = should_stop
        self.rng = random.Random()
        books = db.scalars(select(Book).options(selectinload(Book.authors))).all()
        self.isbns = {b.isbn for b in books}
        self.title_author = {
            (normalise_title(b.title), normalise_name(b.authors[0].name))
            for b in books
            if b.authors
        }
        self.categories = {c.name: c for c in db.scalars(select(Category))}
        self.series = {s.name: s for s in db.scalars(select(Series))}
        self.authors = {a.name: a for a in db.scalars(select(Author))}

    # ------------------------------------------------------------- entry point
    def run(
        self,
        subjects: list[str] | None = None,
        per_subject: int | None = None,
        since_year: int | None = None,
        isbns: list[str] | None = None,
        dry_run: bool = False,
        trigger: str = "manual",
    ) -> SyncReport:
        settings = self.settings
        subjects = (
            settings.sync_subject_list if subjects is None and not isbns else (subjects or [])
        )
        per_subject = per_subject or settings.sync_per_subject
        since_year = since_year or datetime.now().year - settings.sync_since_years
        report = SyncReport()
        run = None
        if not dry_run:
            run = SyncRun(trigger=trigger)
            self.db.add(run)
            self.db.commit()

        try:
            for isbn in isbns or []:
                if self._stop(report):
                    break
                self._from_isbn(isbn.strip(), report, dry_run)
            for subject in subjects:
                if self._stop(report):
                    break
                self._from_subject(subject, per_subject, since_year, report, dry_run)
        except Exception as exc:  # keep a record of what went wrong, then re-raise
            report.errors.append(str(exc))
            raise
        finally:
            if run is not None:
                run.finished_at = utcnow()
                run.added = len(report.added)
                run.skipped = sum(report.skipped.values())
                run.error = "\n".join(report.errors)[:4000]
                self.db.commit()
            if report.added and not dry_run:
                state.reset()  # rebuild the recommender with the new books
        log.info("Catalogue sync (%s): %s", trigger, report.summary())
        return report

    def _stop(self, report: SyncReport) -> bool:
        if self.should_stop():
            report.stopped = True
        return report.stopped

    # ---------------------------------------------------------------- sources
    def _from_subject(self, subject, per_subject, since_year, report, dry_run) -> None:
        genre = map_subjects([subject], set(self.categories))
        try:
            docs = sources.search_popular(self.http, subject, since_year)
        except SourceError as exc:
            report.errors.append(f"search {subject!r}: {exc}")
            return
        added = 0
        for doc in docs[: per_subject * SCAN_FACTOR]:
            if added >= per_subject or self._stop(report):
                break
            reason = self._precheck(doc)
            if reason:
                report.skipped[reason] += 1
                continue
            try:
                book = self._build(doc, extra_genres=genre)
            except SourceError as exc:
                report.errors.append(f"{doc.get('title')}: {exc}")
                continue
            if isinstance(book, str):
                report.skipped[book] += 1
                continue
            self._save(book, dry_run)
            report.added.append(f"{book.title} ({', '.join(book.authors)})")
            added += 1

    def _from_isbn(self, isbn: str, report: SyncReport, dry_run: bool) -> None:
        isbn = re.sub(r"[^0-9Xx]", "", isbn)
        if len(isbn) == 10:
            isbn = sources.isbn10_to_13(isbn) or isbn
        if not sources.valid_isbn13(isbn):
            report.skipped["invalid ISBN"] += 1
            return
        if isbn in self.isbns:
            report.skipped["already in the library"] += 1
            return
        try:
            doc = sources.search_isbn(self.http, isbn)
            if doc is None:
                report.skipped["not found"] += 1
                return
            reason = self._precheck(doc, require_popular=False)
            if reason:
                report.skipped[reason] += 1
                return
            book = self._build(doc, preferred_isbn=isbn)
        except SourceError as exc:
            report.errors.append(f"{isbn}: {exc}")
            return
        if isinstance(book, str):
            report.skipped[book] += 1
            return
        self._save(book, dry_run)
        report.added.append(f"{book.title} ({', '.join(book.authors)})")

    # -------------------------------------------------------------- building
    def _precheck(self, doc: dict, require_popular: bool = True) -> str | None:
        """Cheap checks on a search result, before spending requests on it."""
        title, authors = doc.get("title") or "", doc.get("author_name") or []
        if not title or not authors or not doc.get("key"):
            return "incomplete record"
        if JUNK_TITLE.search(title):
            return "not a single novel (summary, box set, ...)"
        if (normalise_title(title), normalise_name(authors[0])) in self.title_author:
            return "already in the library"
        if require_popular and (doc.get("readinglog_count") or 0) < MIN_READERS:
            return "too few readers"
        if require_popular and not doc.get("cover_i"):
            return "no cover"
        return None

    def _build(
        self, doc: dict, extra_genres: list[str] | None = None, preferred_isbn: str | None = None
    ) -> NewBook | str:
        """A complete NewBook, or the reason this book was skipped."""
        work_key = doc["key"]
        work = sources.get_work(self.http, work_key)
        if preferred_isbn:
            edition = sources.get_edition_by_isbn(self.http, preferred_isbn) or {}
            isbn = preferred_isbn
        else:
            edition = sources.pick_edition(sources.get_editions(self.http, work_key)) or {}
            isbn = sources.edition_isbn13(edition)
        if not isbn:
            return "no English edition with an ISBN"
        if isbn in self.isbns:
            return "already in the library"

        description = sources.clean_description(sources.text_value(work.get("description")))
        pages = edition.get("number_of_pages") or doc.get("number_of_pages_median")
        cover_id = (
            doc.get("cover_i")
            or _first_positive(work.get("covers"))
            or _first_positive(edition.get("covers"))
        )
        cover = sources.cover_url(cover_id)
        subjects = list(doc.get("subject") or []) + list(work.get("subjects") or [])

        if len(description) < MIN_DESCRIPTION or not pages or not cover:
            google = sources.google_lookup(self.http, isbn, self.settings.google_books_api_key)
            if google:
                if len(google.description) > len(description):
                    description = google.description
                pages = pages or google.pages
                cover = cover or google.cover_url
                subjects += google.categories

        if len(description) < MIN_DESCRIPTION:
            return "no description"
        if not cover:
            return "no cover"
        genres = map_subjects(subjects, set(self.categories))
        for name in extra_genres or []:
            if name not in genres:
                genres.insert(0, name)
        if not [g for g in genres if g != "Fiction"]:
            return "no matching genre"

        try:
            pages = int(pages) if pages else None
        except (TypeError, ValueError):
            pages = None
        if pages is not None and not 30 <= pages <= 3000:
            pages = None

        authors = []
        for name in doc.get("author_name") or []:
            name = " ".join(name.split())
            if name and name not in authors:
                authors.append(name)

        return NewBook(
            isbn=isbn,
            title=" ".join((doc.get("title") or work.get("title") or "").split()),
            authors=authors[:3],
            year=doc.get("first_publish_year"),
            pages=pages,
            publisher=" ".join(((edition.get("publishers") or [""])[0]).split())[:255],
            description=description[:6000],
            cover_url=cover,
            categories=genres[:8],
            series=self._match_series(edition.get("series") or []),
        )

    def _match_series(self, raw: list[str]) -> str | None:
        """Link to a series the library already knows; never invent one."""
        for text in raw:
            text = text.lower()
            for name in sorted(self.series, key=len, reverse=True):
                if name.lower() in text:
                    return name
        return None

    # ---------------------------------------------------------------- saving
    def _save(self, new: NewBook, dry_run: bool) -> None:
        self.isbns.add(new.isbn)
        self.title_author.add((normalise_title(new.title), normalise_name(new.authors[0])))
        if dry_run:
            return
        book = Book(
            isbn=new.isbn,
            title=new.title,
            publisher=new.publisher,
            description=new.description,
            year=new.year,
            pages=new.pages,
            cover_url=new.cover_url,
            added_at=utcnow(),
        )
        book.authors = [self._author(name) for name in new.authors]
        book.categories = [self.categories[name] for name in new.categories]
        if new.series:
            book.series = self.series[new.series]
        book.copies = [
            Copy(condition="New", shelf=f"{self.rng.randint(1, 9)}-{self.rng.randint(1, 9)}")
            for _ in range(COPIES_PER_BOOK)
        ]
        self.db.add(book)
        self.db.commit()

    def _author(self, name: str) -> Author:
        if name not in self.authors:
            self.authors[name] = Author(name=name)
        return self.authors[name]


def _first_positive(values) -> int | None:
    for value in values or []:
        if isinstance(value, int) and value > 0:
            return value
    return None


def run_sync(
    db: Session,
    settings: Settings,
    trigger: str = "manual",
    should_stop: Callable[[], bool] = lambda: False,
    **options,
) -> SyncReport:
    http = Http(settings.sync_contact_email)
    try:
        return CatalogueSync(db, http, settings, should_stop).run(trigger=trigger, **options)
    finally:
        http.close()
