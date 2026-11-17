"""Map the messy subject strings of book APIs onto the library's own genres.

Open Library subjects look like "Fiction, fantasy, epic", "Magic -- Fiction"
or "nyt:hardcover-fiction=2024-01-07"; Google Books uses "Fiction / Fantasy /
Epic". New books only ever get genres the library already has, so the genre
list stays clean and the recommender's genre signal keeps working.
"""

from __future__ import annotations

import re

# How the APIs say it -> the library's genre name.
ALIASES: dict[str, str] = {
    "science fiction": "Science Fiction",
    "sci-fi": "Science Fiction",
    "space opera": "Space Opera",
    "dystopias": "Dystopia",
    "dystopian": "Dystopia",
    "fantasy fiction": "Fantasy",
    "epic": "Epic Fantasy",
    "epic fantasy": "Epic Fantasy",
    "high fantasy": "High Fantasy",
    "romantasy": "Romantasy",
    "urban fantasy": "Urban Fantasy",
    "paranormal": "Paranormal",
    "detective and mystery stories": "Mystery",
    "mystery fiction": "Mystery",
    "mystery and detective stories": "Mystery",
    "private investigators": "Detective Fiction",
    "detective": "Detective Fiction",
    "cozy": "Cozy Mystery",
    "murder": "Crime",
    "crime fiction": "Crime",
    "suspense": "Suspense",
    "suspense fiction": "Suspense",
    "thrillers": "Thriller",
    "thriller": "Thriller",
    "psychological": "Psychological Thriller",
    "psychological fiction": "Psychological Thriller",
    "domestic fiction": "Contemporary",
    "love stories": "Romance",
    "romance fiction": "Romance",
    "romantic suspense": "Romance",
    "contemporary romance": "Contemporary Romance",
    "young adult fiction": "Young Adult",
    "young adult": "Young Adult",
    "teen": "Young Adult",
    "juvenile fiction": "Middle Grade",
    "children's fiction": "Childrens",
    "children's stories": "Childrens",
    "historical fiction": "Historical Fiction",
    "historical": "Historical Fiction",
    "horror fiction": "Horror",
    "horror tales": "Horror",
    "ghost stories": "Horror",
    "gothic fiction": "Gothic",
    "vampires": "Vampires",
    "witches": "Witches",
    "dragons": "Dragons",
    "fairies": "Fae",
    "magic": "Magic",
    "mythology, greek": "Greek Mythology",
    "greek mythology": "Greek Mythology",
    "gods, greek": "Greek Mythology",
    "mythology": "Mythology",
    "retellings": "Retellings",
    "humorous fiction": "Humor",
    "humor": "Humor",
    "literary": "Literary Fiction",
    "literary fiction": "Literary Fiction",
    "coming of age": "Coming Of Age",
    "lgbtq+": "LGBTQ+",
    "lgbtq": "LGBTQ+",
    "lgbt": "LGBTQ+",
    "gay men": "LGBTQ+",
    "lesbians": "LGBTQ+",
    "biography & autobiography": "Biography",
    "biography": "Biography",
    "autobiography": "Memoir",
    "memoir": "Memoir",
    "self-help": "Self Help",
    "self help": "Self Help",
    "psychology": "Psychology",
    "history": "History",
    "world war, 1939-1945": "World War II",
    "nonfiction": "Nonfiction",
    "non-fiction": "Nonfiction",
    "short stories": "Short Stories",
    "poetry": "Poetry",
    "graphic novels": "Graphic Novels",
    "comics & graphic novels": "Graphic Novels",
    "adventure stories": "Adventure",
    "action & adventure": "Adventure",
    "adventure": "Adventure",
    "classics": "Classics",
    "fiction": "Fiction",
}

# Subjects that describe the record, not the book: bestseller lists, awards, formats.
NOISE = re.compile(
    r"^(nyt:|new york times|award|accessible book|protected daisy|in library|"
    r"large type|open library|lending library|reading level|fiction in english|"
    r"english fiction|american fiction|general$)",
    re.I,
)
MAX_GENRES = 8


def _parts(subject: str) -> list[str]:
    """'Fiction, fantasy, epic' -> ['fiction, fantasy, epic', 'fiction', 'fantasy', 'epic']."""
    subject = re.sub(r"\s+", " ", subject.strip().lower())
    pieces = [p.strip() for p in re.split(r"\s*(?:--|/|,|;|\(|\))\s*", subject) if p.strip()]
    return [subject, *pieces]


def map_subjects(subjects: list[str], known: set[str]) -> list[str]:
    """Return library genres (from `known`) that these subjects describe."""
    by_lower = {name.lower(): name for name in known}
    found: list[str] = []

    def take(name: str | None) -> None:
        if name and name in known and name not in found:
            found.append(name)

    for subject in subjects:
        if not subject or NOISE.search(subject.strip()):
            continue
        for part in _parts(subject):
            take(by_lower.get(part))
            take(ALIASES.get(part))
    # "Fiction" says little; keep it, but last, and only if there is room.
    found.sort(key=lambda name: name == "Fiction")
    return found[:MAX_GENRES]
