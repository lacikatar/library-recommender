"""The catalogue sync, run against fake Open Library and Google Books servers."""

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.config import Settings
from app.models import Book, SyncRun, utcnow
from app.sync import catalogue, sources
from app.sync.catalogue import CatalogueSync
from app.sync.genres import map_subjects
from app.sync.sources import Http


def isbn13(n: int) -> str:
    core = f"978{n:09d}"
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


LONG = "A sharp, atmospheric story about secrets, family and the price of ambition. " * 4

# work key -> (search doc, work record, editions, google description or None)
WORKS = {
    "/works/OL1W": dict(
        doc={
            "title": "The Glass Orchard",
            "author_name": ["Mira  Okafor"],
            "first_publish_year": 2024,
            "subject": [
                "Fiction, fantasy, epic",
                "Magic -- Fiction",
                "nyt:hardcover-fiction=2024-05-01",
            ],
            "cover_i": 101,
            "readinglog_count": 900,
        },
        work={
            "description": {
                "type": "/type/text",
                "value": LONG
                + "\r\n\r\n----------\r\nAlso contained in:\r\n[1]: https://example.com",
            },
            "subjects": ["Dragons"],
        },
        editions=[
            {
                "isbn_13": [isbn13(1)],
                "languages": [{"key": "/languages/fre"}],
                "number_of_pages": 400,
            },
            {
                "isbn_13": [isbn13(2)],
                "languages": [{"key": "/languages/eng"}],
                "physical_format": "ebook",
            },
            {
                "isbn_13": [isbn13(3)],
                "languages": [{"key": "/languages/eng"}],
                "physical_format": "Paperback",
                "number_of_pages": 432,
                "publishers": ["Orbit"],
                "series": ["Shadow and Bone ; 4"],
            },
        ],
    ),
    "/works/OL2W": dict(  # no description on Open Library: Google Books fills it in
        doc={
            "title": "Salt and Iron",
            "author_name": ["Teo Brandt"],
            "first_publish_year": 2023,
            "subject": ["Fantasy fiction"],
            "cover_i": 102,
            "readinglog_count": 400,
        },
        work={},
        editions=[{"isbn_10": ["0306406152"], "languages": [{"key": "/languages/eng"}]}],
        google="<p>The <b>last</b> smith of a drowned kingdom forges a blade for a queen.</p><p>"
        + LONG
        + "</p>",
    ),
    "/works/OL3W": dict(  # already in the library under another edition
        doc={
            "title": "Circe",
            "author_name": ["Madeline Miller"],
            "first_publish_year": 2018,
            "cover_i": 103,
            "readinglog_count": 5000,
        },
        work={},
        editions=[],
    ),
    "/works/OL4W": dict(
        doc={
            "title": "Summary of The Glass Orchard",
            "author_name": ["Quick Reads"],
            "cover_i": 104,
            "readinglog_count": 50,
        },
        work={},
        editions=[],
    ),
    "/works/OL5W": dict(
        doc={
            "title": "Obscure Draft",
            "author_name": ["Nobody"],
            "cover_i": 105,
            "readinglog_count": 2,
        },
        work={},
        editions=[],
    ),
    "/works/OL6W": dict(  # no description anywhere
        doc={
            "title": "The Quiet Fen",
            "author_name": ["A. Marsh"],
            "cover_i": 106,
            "readinglog_count": 300,
        },
        work={"description": "Short."},
        editions=[{"isbn_13": [isbn13(6)], "languages": [{"key": "/languages/eng"}]}],
    ),
    "/works/OL7W": dict(
        doc={
            "title": "Night Market",
            "author_name": ["June Park"],
            "first_publish_year": 2025,
            "subject": ["Fantasy"],
            "cover_i": 107,
            "readinglog_count": 300,
        },
        work={"description": LONG, "subjects": ["Young adult fiction"]},
        editions=[
            {
                "isbn_13": [isbn13(7)],
                "languages": [{"key": "/languages/eng"}],
                "number_of_pages": 300,
            }
        ],
    ),
    "/works/OL8W": dict(
        doc={
            "title": "The Long Thaw",
            "author_name": ["R. Vale"],
            "first_publish_year": 2024,
            "subject": ["Fantasy"],
            "cover_i": 108,
            "readinglog_count": 200,
        },
        work={"description": LONG},
        editions=[
            {
                "isbn_13": [isbn13(8)],
                "languages": [{"key": "/languages/eng"}],
                "number_of_pages": 310,
            }
        ],
    ),
}


class FakeApis:
    def __init__(self, reject_sort=False, flaky=0):
        self.calls: list[str] = []
        self.reject_sort = reject_sort
        self.flaky = flaky

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append(url.path)
        assert request.headers["User-Agent"].startswith("LacisLibrary/")
        if self.flaky:
            self.flaky -= 1
            return httpx.Response(503)
        if url.netloc == "www.googleapis.com":
            for work in WORKS.values():
                for e in work["editions"]:
                    if sources.edition_isbn13(e) == query["q"].removeprefix("isbn:") and work.get(
                        "google"
                    ):
                        return _json(
                            {
                                "items": [
                                    {
                                        "volumeInfo": {
                                            "description": work["google"],
                                            "pageCount": 288,
                                            "categories": ["Fiction / Fantasy / Epic"],
                                        }
                                    }
                                ]
                            }
                        )
            return _json({"totalItems": 0})
        if url.path == "/search.json":
            if self.reject_sort and "sort" in query:
                return httpx.Response(400)
            if query["q"].startswith("isbn:"):
                wanted = query["q"].removeprefix("isbn:")
                for key, work in WORKS.items():
                    if any(sources.edition_isbn13(e) == wanted for e in work["editions"]):
                        return _json({"docs": [{"key": key, **work["doc"]}]})
                return _json({"docs": []})
            return _json({"docs": [{"key": k, **w["doc"]} for k, w in WORKS.items()]})
        if url.path.startswith("/isbn/"):
            wanted = url.path.split("/")[-1].removesuffix(".json")
            for work in WORKS.values():
                for e in work["editions"]:
                    if sources.edition_isbn13(e) == wanted:
                        return _json(e)
            return httpx.Response(404)
        if url.path.endswith("/editions.json"):
            return _json({"entries": WORKS[url.path.removesuffix("/editions.json")]["editions"]})
        if url.path.endswith(".json"):
            return _json(WORKS[url.path.removesuffix(".json")]["work"])
        return httpx.Response(404)


def _json(data) -> httpx.Response:
    return httpx.Response(
        200, content=json.dumps(data), headers={"Content-Type": "application/json"}
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)


def make_sync(db, apis=None, **settings):
    http = Http("me@example.com", transport=httpx.MockTransport(apis or FakeApis()), min_interval=0)
    return CatalogueSync(db, http, Settings(**settings))


# ------------------------------------------------------------------ the pieces
def test_genre_mapping_uses_only_existing_genres():
    known = {"Fantasy", "Epic Fantasy", "Magic", "Fiction", "Mystery", "Young Adult"}
    assert map_subjects(
        ["Fiction, fantasy, epic", "Magic -- Fiction", "nyt:bestseller"], known
    ) == ["Fantasy", "Epic Fantasy", "Magic", "Fiction"]
    assert map_subjects(["Detective and mystery stories", "Space aliens"], known) == ["Mystery"]
    assert map_subjects(["Young adult fiction"], known) == ["Young Adult"]


def test_description_cleaning():
    raw = "<p>One &amp; two.</p><p>See [the site][1] and [docs](http://x).</p>\n\n----------\nAlso in: [1]: http://y"
    assert sources.clean_description(raw) == "One & two.\n\nSee the site and docs."
    assert sources.text_value({"type": "/type/text", "value": "hi"}) == "hi"


def test_isbns_and_edition_choice():
    assert sources.isbn10_to_13("0-306-40615-2") == "9780306406157"
    assert sources.valid_isbn13("9780306406157") and not sources.valid_isbn13("9780306406158")
    chosen = sources.pick_edition(WORKS["/works/OL1W"]["editions"])
    assert sources.edition_isbn13(chosen) == isbn13(3)  # English paperback, not French or ebook


def test_http_retries_server_errors_but_not_bad_requests():
    apis = FakeApis(flaky=2)
    http = Http(transport=httpx.MockTransport(apis), min_interval=0)
    assert http.get("https://openlibrary.org/works/OL7W.json")["description"] == LONG
    assert len(apis.calls) == 3
    with pytest.raises(sources.SourceError):
        Http(transport=httpx.MockTransport(lambda r: httpx.Response(400)), min_interval=0).get(
            "https://x.org/a"
        )


# --------------------------------------------------------------- a whole run
def test_sync_adds_complete_books_and_skips_the_rest(client, db):
    before = db.query(Book).count()
    report = make_sync(db).run(subjects=["fantasy"], per_subject=10, since_year=2020)

    assert sorted(report.added) == [
        "Night Market (June Park)",
        "Salt and Iron (Teo Brandt)",
        "The Glass Orchard (Mira Okafor)",
        "The Long Thaw (R. Vale)",
    ]
    assert report.skipped == {
        "already in the library": 1,
        "not a single novel (summary, box set, ...)": 1,
        "too few readers": 1,
        "no description": 1,
    }
    assert db.query(Book).count() == before + 4

    orchard = db.get(Book, isbn13(3))
    assert orchard.publisher == "Orbit" and orchard.pages == 432 and orchard.year == 2024
    assert orchard.description == LONG.strip()  # Open Library footer removed
    assert orchard.cover_url == "https://covers.openlibrary.org/b/id/101-L.jpg"
    assert [a.name for a in orchard.authors] == ["Mira Okafor"]
    assert {c.name for c in orchard.categories} >= {"Fantasy", "Epic Fantasy", "Magic", "Dragons"}
    assert orchard.series.name == "Shadow and Bone"  # linked to a series the library has
    assert len(orchard.copies) == 2 and orchard.added_at is not None

    salt = db.get(Book, "9780306406157")  # ISBN-10 converted
    assert salt.description.startswith("The last smith of a drowned kingdom")
    assert salt.pages == 288

    run = db.scalar(select(SyncRun))
    assert run.added == 4 and run.finished_at and run.trigger == "manual"


def test_sync_is_idempotent_and_dry_run_saves_nothing(client, db):
    assert make_sync(db).run(subjects=["fantasy"], per_subject=10, dry_run=True).added
    assert db.query(Book).filter(Book.added_at.is_not(None)).count() == 0
    assert db.scalar(select(SyncRun)) is None

    make_sync(db).run(subjects=["fantasy"], per_subject=10)
    again = make_sync(db).run(subjects=["fantasy"], per_subject=10)
    assert again.added == []


def test_sync_by_isbn(client, db):
    report = make_sync(db).run(isbns=[isbn13(7), isbn13(7), "123", isbn13(999)])
    assert report.added == ["Night Market (June Park)"]
    assert report.skipped == {"already in the library": 1, "invalid ISBN": 1, "not found": 1}


def test_falls_back_when_the_sort_option_is_rejected(client, db):
    apis = FakeApis(reject_sort=True)
    assert make_sync(db, apis).run(subjects=["fantasy"], per_subject=1).added


def test_new_books_reach_search_recommendations_and_the_home_page(client, db):
    make_sync(db).run(subjects=["fantasy"], per_subject=10)
    found = client.get("/api/books", params={"q": "glass orchard"}).json()["items"]
    assert found[0]["title"] == "The Glass Orchard"
    similar = client.get(f"/api/books/{isbn13(3)}/similar").json()
    assert similar and all(b["isbn"] != isbn13(3) for b in similar)
    shelves = {s["title"]: s for s in client.get("/api/recommendations/home").json()["shelves"]}
    assert len(shelves["New on the shelves"]["books"]) == 4
    newest = client.get("/api/books", params={"sort": "added", "page_size": 4}).json()["items"]
    assert {b["title"] for b in newest} >= {"The Glass Orchard", "Night Market"}
    updates = client.get("/api/catalogue/updates").json()
    assert updates["books_added_total"] == 4 and updates["last_run"]["added"] == 4


def test_books_added_by_another_process_are_picked_up(client, db):
    client.get("/api/recommendations/home")  # engine built
    # Simulate the CLI: a separate session writes a book, with no in-process reset.
    monkey_reset = catalogue.state.reset
    catalogue.state.reset = lambda: None
    try:
        make_sync(db).run(subjects=["fantasy"], per_subject=1)
    finally:
        catalogue.state.reset = monkey_reset
    found = client.get("/api/books", params={"q": "glass orchard"}).json()["items"]
    assert found and found[0]["title"] == "The Glass Orchard"


def test_stop_request_ends_the_run_early(client, db):
    sync = make_sync(db)
    sync.should_stop = lambda: True
    report = sync.run(subjects=["fantasy", "mystery"], per_subject=10)
    assert report.stopped and report.added == []


# --------------------------------------------------------- schedule and schema
def test_schedule_waits_for_the_interval(client, db):
    from app.sync.scheduler import seconds_until_due

    assert seconds_until_due(24) == 0  # never ran
    db.add(SyncRun(finished_at=utcnow() - timedelta(hours=20)))
    db.commit()
    assert 3.9 * 3600 < seconds_until_due(24) <= 4 * 3600
    # A failed run (no network) is retried after an hour, not the next day...
    db.add(SyncRun(finished_at=utcnow() - timedelta(minutes=10), error="offline"))
    db.commit()
    assert (
        3.9 * 3600 < seconds_until_due(24) <= 4 * 3600
    )  # ...unless a good run is due later anyway
    db.query(SyncRun).delete()
    db.add(SyncRun(finished_at=utcnow() - timedelta(minutes=10), error="offline"))
    db.commit()
    assert 49 * 60 < seconds_until_due(24) <= 50 * 60


def test_upgrade_adds_the_new_column_to_an_old_database(tmp_path):
    from app.migrations import upgrade

    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE books (isbn VARCHAR(13) PRIMARY KEY, title VARCHAR(255))"))
    assert upgrade(old) == ["books.added_at"]
    assert "added_at" in {c["name"] for c in inspect(old).get_columns("books")}
    assert upgrade(old) == []  # safe to run again


def test_command_line(client, db, monkeypatch, capsys):
    from app.sync import __main__ as cli

    seen = {}

    def fake_run(db, settings, **options):
        seen.update(options)
        return catalogue.SyncReport(added=["X (Y)"])

    monkeypatch.setattr(cli, "run_sync", fake_run)
    assert (
        cli.main(
            [
                "--subject",
                "cozy mystery",
                "--per-subject",
                "2",
                "--isbn",
                "9780306406157",
                "--dry-run",
            ]
        )
        == 0
    )
    assert seen["subjects"] == ["cozy mystery"] and seen["per_subject"] == 2
    assert seen["isbns"] == ["9780306406157"] and seen["dry_run"] is True
    assert "Would add 1 books" in capsys.readouterr().out
