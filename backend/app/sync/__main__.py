"""Add new books from the command line.

python -m app.sync                         # the subjects in your settings
python -m app.sync --subject "cozy mystery" --per-subject 5
python -m app.sync --isbn 9780593334836 --isbn 9781250178602
python -m app.sync --isbn-file wanted.txt  # one ISBN per line
python -m app.sync --dry-run               # show what would be added
"""

import argparse
import logging
import sys
from pathlib import Path

from ..config import get_settings
from ..db import Base, SessionLocal, engine
from ..migrations import upgrade
from ..seed import seed_if_empty
from .catalogue import run_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.sync",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--subject", action="append", help="subject to search; repeatable")
    parser.add_argument("--per-subject", type=int, help="new books per subject")
    parser.add_argument(
        "--since", type=int, help="only books first published in or after this year"
    )
    parser.add_argument(
        "--isbn", action="append", default=[], help="add this exact book; repeatable"
    )
    parser.add_argument("--isbn-file", type=Path, help="text file with one ISBN per line")
    parser.add_argument("--dry-run", action="store_true", help="look up books but save nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    isbns = list(args.isbn)
    if args.isbn_file:
        isbns += [
            line.strip()
            for line in args.isbn_file.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]

    Base.metadata.create_all(engine)
    upgrade(engine)
    settings = get_settings()
    with SessionLocal() as db:
        seed_if_empty(db)
        report = run_sync(
            db,
            settings,
            trigger="manual",
            subjects=args.subject,
            per_subject=args.per_subject,
            since_year=args.since,
            isbns=isbns,
            dry_run=args.dry_run,
        )

    verb = "Would add" if args.dry_run else "Added"
    print(f"\n{verb} {len(report.added)} books:")
    for title in report.added:
        print(f"  + {title}")
    if report.skipped:
        print("Skipped:")
        for reason, count in report.skipped.most_common():
            print(f"  {count:3d}  {reason}")
    for error in report.errors:
        print(f"  ! {error}", file=sys.stderr)
    if report.added and not args.dry_run:
        print("\nA running server picks the new books up on its next request.")
    return 1 if report.errors and not report.added else 0


if __name__ == "__main__":
    sys.exit(main())
