"""Convert the original phpMyAdmin dump into a clean catalogue.json.

Usage:
    python scripts/import_legacy.py path/to/librarydb.sql data/catalogue.json

Only catalogue tables are read (book, author, wrote, category, belongs,
book_series, copy). Member and staff rows are deliberately ignored, so no
personal data from the old database ends up in the repository.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CATALOGUE_TABLES = {"book", "author", "wrote", "category", "belongs", "book_series", "copy"}

# Goodreads shelves that describe a format or a reading occasion, not a genre.
DROP_CATEGORIES = {"Audiobook", "Book Club", "Read For School", "School", "College", "Novels"}

# Near-duplicate shelves folded into one name.
MERGE_CATEGORIES = {
    "Dystopian Fiction": "Dystopia",
    "Fantasy Fiction": "Fantasy",
    "Mystery Fiction": "Mystery",
    "Horror Fiction": "Horror",
    "Romantic Fiction": "Romance",
    "Young Adult Fiction": "Young Adult",
    "Classic Literature": "Classics",
    "Queer": "LGBTQ+",
    "LGBT": "LGBTQ+",
    "Biography Memoir": "Memoir",
    "Science Fiction Fantasy": "Science Fiction",
}

_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", "'": "'", '"': '"'}


def parse_values(blob: str) -> list[list]:
    """Parse the VALUES part of a MySQL INSERT into a list of rows."""
    rows, row, i, n = [], None, 0, len(blob)
    while i < n:
        ch = blob[i]
        if row is None:
            if ch == "(":
                row = []
            i += 1
            continue
        if ch == "'":
            i += 1
            buf = []
            while i < n:
                c = blob[i]
                if c == "\\" and i + 1 < n:
                    buf.append(_ESCAPES.get(blob[i + 1], blob[i + 1]))
                    i += 2
                elif c == "'":
                    if i + 1 < n and blob[i + 1] == "'":
                        buf.append("'")
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    buf.append(c)
                    i += 1
            row.append("".join(buf))
        elif ch == ")":
            rows.append(row)
            row = None
            i += 1
        elif ch in ", \n\r\t":
            i += 1
        else:
            j = i
            while j < n and blob[j] not in ",)":
                j += 1
            token = blob[i:j].strip()
            if token.upper() == "NULL":
                row.append(None)
            else:
                try:
                    row.append(int(token))
                except ValueError:
                    row.append(float(token))
            i = j
    return rows


def read_tables(sql: str) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = defaultdict(list)
    pattern = re.compile(r"INSERT INTO `(\w+)` \(([^)]*)\) VALUES\s*\n", re.S)
    for match in pattern.finditer(sql):
        table = match.group(1)
        if table not in CATALOGUE_TABLES:
            continue
        columns = [c.strip(" `") for c in match.group(2).split(",")]
        end = _statement_end(sql, match.end())
        for row in parse_values(sql[match.end() : end]):
            tables[table].append(dict(zip(columns, row)))
    return tables


def _statement_end(sql: str, start: int) -> int:
    """Index of the ';' that closes the statement, skipping quoted text."""
    i, in_string = start, False
    while i < len(sql):
        c = sql[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == "'":
                in_string = False
        elif c == "'":
            in_string = True
        elif c == ";":
            return i
        i += 1
    return len(sql)


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_catalogue(tables: dict[str, list[dict]]) -> dict:
    authors = {a["Author_ID"]: " ".join(a["Name"].split()) for a in tables["author"]}
    # "The Chronicles of Narnia (Chronological Order)" -> "The Chronicles of Narnia"
    series = {
        s["Series_ID"]: re.sub(r"\s*\([^)]*\)\s*$", "", s["Name"]).strip()
        for s in tables["book_series"]
    }
    categories = {c["Category_ID"]: c["Name"].strip() for c in tables["category"]}

    book_authors: dict[str, list[str]] = defaultdict(list)
    for row in tables["wrote"]:
        name = authors.get(row["Author_ID"])
        if name and name not in book_authors[row["ISBN"]]:
            book_authors[row["ISBN"]].append(name)

    book_categories: dict[str, list[str]] = defaultdict(list)
    for row in tables["belongs"]:
        name = categories.get(row["Category_ID"])
        if not name or name in DROP_CATEGORIES:
            continue
        name = MERGE_CATEGORIES.get(name, name)
        if name not in book_categories[row["ISBN"]]:
            book_categories[row["ISBN"]].append(name)

    copies: dict[str, list[dict]] = defaultdict(list)
    for row in tables["copy"]:
        copies[row["ISBN"]].append(
            {"condition": row["Copy_Condition"], "shelf": row["Shelf_Position"]}
        )

    books = []
    for b in tables["book"]:
        isbn = b["ISBN"]
        books.append(
            {
                "isbn": isbn,
                "title": " ".join(b["Title"].replace("\u200b", "").split()),
                "authors": book_authors.get(isbn, []),
                "series": series.get(b["Series_ID"]),
                "publisher": (b["Publisher"] or "").strip(),
                "year": b["Release_Year"],
                "pages": b["Page_Nr"],
                "description": clean_text(b["Description"]),
                "cover_url": b["Image_URL"],
                "categories": sorted(book_categories.get(isbn, [])),
                "copies": copies.get(isbn, []),
            }
        )
    books.sort(key=lambda x: x["title"].lower())
    return {"books": books}


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sql = Path(sys.argv[1]).read_text(encoding="utf-8")
    catalogue = build_catalogue(read_tables(sql))
    Path(sys.argv[2]).write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    books = catalogue["books"]
    print(
        f"{len(books)} books, "
        f"{len({a for b in books for a in b['authors']})} authors, "
        f"{len({c for b in books for c in b['categories']})} categories, "
        f"{sum(len(b['copies']) for b in books)} copies"
    )


if __name__ == "__main__":
    main()
