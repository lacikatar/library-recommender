# Laci's Library

A library catalogue that learns what you like to read. Browse 251 books, borrow
and return them, keep shelves and reading lists, and get recommendations that
explain themselves. Ask for a book in plain language ("something like Dune but
shorter") and the librarian finds it.

Started as a university database project in PHP and MySQL; rebuilt as a Python
API with a React frontend.

## Run it

You need Python 3.11+ and Node 20+.

```bash
# 1. API (creates the database and demo data on first start)
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows.  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 2. Frontend, in a second terminal
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and log in as **demo** / **demo1234**, or register.

To run it as one process (how it would be deployed), build the frontend and
let the API serve it:

```bash
cd frontend && npm run build
cd ../backend && uvicorn app.main:app        # http://localhost:8000
```

Or with Docker: `docker build -t library . && docker run -p 8000:8000 -v library-data:/data -e SECRET_KEY=change-me library`

## What it does

| | |
|---|---|
| **Catalogue** | Search by title, author or theme; filter by genre and availability; browse authors, genres and series |
| **Lending** | Borrow and return copies, 21-day loans, a limit of five, first-come-first-served waitlists |
| **Shelves** | Want to read / reading / read, star ratings, reviews, named reading lists |
| **For you** | One personalised feed. Every pick states its reason, can be expanded to show what drove it, and can be dismissed |
| **Ask the librarian** | Natural-language requests, answered from the library's own shelves |

## How the recommender works

There is one ranker (`backend/app/recsys/engine.py`), not a menu of algorithms.
For each unread book it blends four signals:

1. **Taste**: similarity to books the reader liked. Each book is represented by
   TF-IDF of its description compressed with truncated SVD (latent semantic
   analysis), its genres weighted by inverse frequency, and its author and series.
2. **Community**: item-item collaborative filtering over every reader's ratings,
   shelves and loans, using a shrunk cosine so that pairs backed by few readers
   count for less.
3. **Favourite genres**: chosen at sign-up, for the cold start.
4. **Popularity**: reach plus a Bayesian-smoothed average rating.

The weights move with how much is known about the reader. With no history,
genres and popularity decide. One five-star rating shifts about 40% of the
weight to taste and community; six shift about three quarters.

Then:

- the next unread book of a series the reader is following is boosted;
- low ratings and "Not interested" push similar books down;
- the list is diversified with maximal marginal relevance, one book per series;
- each pick gets a reason from its strongest signal ("Because you rated Six of
  Crows 5★", "Readers who enjoyed Dune also enjoyed this", "Next up in ...").

Nothing is precomputed into tables. The content model is built once at start-up
and reader behaviour is reloaded on change, so a new rating changes the feed on
the next request. A full ranking takes about a millisecond at this size; for a
much larger catalogue the same vectors would go into an approximate
nearest-neighbour index.

### Ask the librarian

`recsys/query.py` reads a request for genres (with everyday aliases such as
"sci-fi" or "YA"), an author, a book or series to compare with, page count and
publication date, and matches the remaining words against descriptions. This
needs no API key.

If `LLM_API_KEY` is set (`backend/.env.example`), an LLM chooses up to five
books from that shortlist and writes a sentence about each. This is
retrieval-augmented generation with a hard guard: any ISBN in the model's
answer that is not in the shortlist is discarded, so it cannot recommend a book
the library does not own. If the call fails, the built-in ranking is returned.

## Adding new books automatically

The catalogue grows on its own. A sync job asks [Open Library](https://openlibrary.org/developers/api)
for the most-read English books first published in the last few years in each
subject you choose, skips anything the library already has, and fills in each new
book: authors, year, genres, description, cover, page count and an ISBN. Where
Open Library has no description or page count, it asks Google Books. A book is
added only if it ends up with a real description, a cover and at least one of the
library's genres, since a book without those cannot be recommended well.

New books get two copies, appear in a "New on the shelves" row on the home page and
under **Browse → Sort by → Recently added**, and the recommender picks them up on
the next request.

**On a schedule.** Copy `backend/.env.example` to `backend/.env` and set
`SYNC_INTERVAL_HOURS=24`. While the API is running it adds books once a day
(the first run starts 30 seconds after start-up). Restarting the server does not
trigger extra runs, and a failed run (no internet) is retried after an hour.

**By hand.**

```bash
cd backend
python -m app.sync --dry-run                      # show what would be added, save nothing
python -m app.sync                                # the subjects in your settings
python -m app.sync --subject "cozy mystery" --per-subject 5
python -m app.sync --isbn 9780593334836           # one exact book; repeatable
python -m app.sync --isbn-file wanted.txt         # one ISBN per line
```

The sync is deliberately gentle: Open Library asks apps not to bulk-download
through its API, so each run adds a few books per subject and waits between
requests. Set `SYNC_CONTACT_EMAIL` so Open Library knows who is calling.

Genres are mapped onto the library's existing list (`app/sync/genres.py`), never
created, so the genre filter and the recommender's genre signal stay clean. Series
are only linked when the series already exists in the library.

## Project layout

```
backend/
  app/
    main.py            FastAPI app; serves the built frontend in production
    models.py          SQLAlchemy models (SQLite by default)
    security.py        bcrypt password hashing, session in an httpOnly cookie
    seed.py            loads the catalogue, invents demo readers
    routers/           auth, catalogue, library (loans, shelves, lists), recommendations
    sync/              the catalogue sync: sources, genre mapping, schedule, CLI
    migrations.py      adds new columns to databases made by older versions
    recsys/
      content.py       what each book is about
      engine.py        the hybrid ranker and its explanations
      query.py         natural-language request -> shortlist
      assistant.py     optional LLM layer, grounded in the shortlist
  data/catalogue.json  the 251 books
  scripts/import_legacy.py   one-off converter from the original MySQL dump
  tests/               46 tests
frontend/
  src/pages/           one file per screen
  src/components/      book cards, shelves, layout
```

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

They cover the ranker in isolation (cold start, exclusions, series, dislikes,
collaborative signal), the feed against the real catalogue, query
understanding, LLM grounding and fallback with a mocked provider, and the
lending rules.

## Data and privacy

- Book metadata, descriptions and cover image links were collected from
  Goodreads for the original coursework. Covers are loaded from their original
  URLs, not stored here.
- The 48 demo readers and their ratings are generated (`seed.py`). No real
  member data is in this repository; the converter reads catalogue tables only.
- To start again with a clean database, delete `backend/library.db`.

## Known limits

- Search and ranking use dense matrices in memory, which suits hundreds of
  books, not hundreds of thousands.
- The librarian answers one request at a time; it does not remember earlier
  questions.
- Description similarity is lexical (LSA). Swapping in sentence embeddings is a
  change to `content.py` only.
- There is no staff interface for editing books or managing copies; new books
  arrive through the sync only.
- Open Library's data is community-edited, so an occasional synced book may have a
  thin description or odd genres. Delete it from the database if it bothers you.
