"""Clients for the two public book APIs the sync reads from.

Open Library (no key) supplies the books: what is popular and recent in a
subject, plus authors, year, genres, description, cover and an English
edition's ISBN. Google Books (no key needed at low volume) fills in a
description or page count when Open Library has none.

Open Library asks apps to send a User-Agent with a contact email and to stay
under 1 request/second (3/second when identified). `Throttle` enforces that,
and failed requests are retried with back-off.
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

OPEN_LIBRARY = "https://openlibrary.org"
COVERS = "https://covers.openlibrary.org/b/id/{id}-L.jpg"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"
SEARCH_FIELDS = (
    "key,title,author_name,first_publish_year,subject,cover_i,"
    "readinglog_count,ratings_average,ratings_count,number_of_pages_median"
)


class SourceError(RuntimeError):
    pass


class Throttle:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


class Http:
    """GET JSON politely: one shared client, throttled, retried."""

    def __init__(
        self,
        contact_email: str = "",
        transport: httpx.BaseTransport | None = None,
        min_interval: float | None = None,
        retries: int = 3,
    ):
        agent = "LacisLibrary/2.0 (portfolio project"
        agent += f"; {contact_email})" if contact_email else ")"
        self.client = httpx.Client(
            headers={"User-Agent": agent, "Accept": "application/json"},
            timeout=20.0,
            follow_redirects=True,
            transport=transport,
        )
        if min_interval is None:
            min_interval = 0.4 if contact_email else 1.1
        self.throttle = Throttle(min_interval)
        self.retries = retries

    def get(self, url: str, params: dict | None = None) -> dict | None:
        """The JSON body, or None for a 404. Raises SourceError on other failures."""
        for attempt in range(self.retries + 1):
            self.throttle.wait()
            try:
                response = self.client.get(url, params=params)
            except httpx.HTTPError as exc:
                error = f"{url}: {exc}"
            else:
                if response.status_code == 404:
                    return None
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SourceError(f"{url}: not JSON") from exc
                error = f"{url}: HTTP {response.status_code}"
                if response.status_code < 500 and response.status_code != 429:
                    raise SourceError(error)  # a bad request will not improve on retry
            if attempt < self.retries:
                time.sleep(min(30, 2**attempt * 2))
        raise SourceError(error)

    def close(self) -> None:
        self.client.close()


# ---------------------------------------------------------------- Open Library
def search_popular(http: Http, subject: str, since_year: int, limit: int = 40) -> list[dict]:
    """Popular English-language works in a subject, first published since `since_year`."""
    query = f'subject:"{subject}" first_publish_year:[{since_year} TO *] language:eng'
    params = {"q": query, "fields": SEARCH_FIELDS, "limit": limit, "sort": "readinglog"}
    try:
        data = http.get(f"{OPEN_LIBRARY}/search.json", params)
    except SourceError:
        # If the sort option is ever renamed, fall back to sorting the results ourselves.
        params.pop("sort")
        data = http.get(f"{OPEN_LIBRARY}/search.json", params)
    docs = (data or {}).get("docs", [])
    return sorted(docs, key=lambda d: -(d.get("readinglog_count") or 0))


def search_isbn(http: Http, isbn: str) -> dict | None:
    data = http.get(
        f"{OPEN_LIBRARY}/search.json", {"q": f"isbn:{isbn}", "fields": SEARCH_FIELDS, "limit": 1}
    )
    docs = (data or {}).get("docs", [])
    return docs[0] if docs else None


def get_work(http: Http, work_key: str) -> dict:
    return http.get(f"{OPEN_LIBRARY}{work_key}.json") or {}


def get_editions(http: Http, work_key: str) -> list[dict]:
    data = http.get(f"{OPEN_LIBRARY}{work_key}/editions.json", {"limit": 50}) or {}
    return data.get("entries", [])


def get_edition_by_isbn(http: Http, isbn: str) -> dict | None:
    return http.get(f"{OPEN_LIBRARY}/isbn/{isbn}.json")


def cover_url(cover_id) -> str | None:
    try:
        return COVERS.format(id=int(cover_id)) if cover_id and int(cover_id) > 0 else None
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- Google Books
@dataclass
class GoogleInfo:
    description: str = ""
    pages: int | None = None
    categories: list[str] = field(default_factory=list)
    cover_url: str | None = None


def google_lookup(http: Http, isbn: str, api_key: str = "") -> GoogleInfo | None:
    params = {"q": f"isbn:{isbn}", "maxResults": 1}
    if api_key:
        params["key"] = api_key
    data = http.get(GOOGLE_BOOKS, params) or {}
    items = data.get("items") or []
    if not items:
        return None
    info = items[0].get("volumeInfo", {})
    links = info.get("imageLinks") or {}
    image = links.get("thumbnail") or links.get("smallThumbnail")
    if image:
        image = image.replace("http://", "https://").replace("&edge=curl", "")
    return GoogleInfo(
        description=clean_description(info.get("description") or ""),
        pages=info.get("pageCount") or None,
        categories=list(info.get("categories") or []),
        cover_url=image,
    )


# ------------------------------------------------------------------- cleaning
def text_value(value) -> str:
    """Open Library stores text either as a string or as {"type": ..., "value": ...}."""
    if isinstance(value, dict):
        value = value.get("value", "")
    return value if isinstance(value, str) else ""


def clean_description(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<\s*(br|/p|p)\s*/?>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)  # remaining HTML tags (Google Books)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Open Library adds footers such as "----------\nAlso contained in: ..." and link lists.
    text = re.split(r"\n\s*-{4,}", text)[0]
    text = re.sub(r"^\s*\[\d+\]:\s*\S+\s*$", "", text, flags=re.M)
    text = re.sub(r"\(\[[^\]]*\]\[\d+\]\)", "", text)  # "([source][1])"
    text = re.sub(r"\[([^\]]+)\]\[\d+\]", r"\1", text)  # "[text][1]" -> "text"
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # markdown links
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def isbn10_to_13(isbn10: str) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", isbn10)
    if len(digits) != 10:
        return None
    core = "978" + digits[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def valid_isbn13(isbn: str) -> bool:
    if not re.fullmatch(r"97[89]\d{10}", isbn):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn[:12]))
    return (10 - total % 10) % 10 == int(isbn[12])


def edition_isbn13(edition: dict) -> str | None:
    for raw in edition.get("isbn_13") or []:
        isbn = re.sub(r"\D", "", raw)
        if valid_isbn13(isbn):
            return isbn
    for raw in edition.get("isbn_10") or []:
        isbn = isbn10_to_13(raw)
        if isbn and valid_isbn13(isbn):
            return isbn
    return None


def pick_edition(editions: list[dict]) -> dict | None:
    """The English print edition with the most complete record."""

    def score(e: dict) -> tuple:
        languages = {lang.get("key", "") for lang in e.get("languages") or []}
        fmt = (e.get("physical_format") or "").lower()
        return (
            "/languages/eng" in languages or not languages,
            not any(word in fmt for word in ("ebook", "e-book", "audio", "kindle", "cd")),
            bool(e.get("number_of_pages")),
            bool(e.get("covers")),
            bool(e.get("publishers")),
        )

    usable = [e for e in editions if edition_isbn13(e)]
    english = [e for e in usable if score(e)[0]]
    return max(english, key=score) if english else None
