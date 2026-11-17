"""Tiny forward-only schema upgrades for databases created by older versions.

`create_all` makes new tables but never changes existing ones, so a column
added later is added here. Each step checks before it acts, so running this
on every start is safe.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

COLUMNS = [
    # (table, column, SQL type)
    ("books", "added_at", "DATETIME"),
]
INDEXES = [
    ("ix_books_added_at", "books", "added_at"),
]


def upgrade(engine: Engine) -> list[str]:
    applied = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, sql_type in COLUMNS:
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
                applied.append(f"{table}.{column}")
        for name, table, column in INDEXES:
            if table in tables and name not in {
                i["name"] for i in inspect(conn).get_indexes(table)
            }:
                conn.execute(text(f"CREATE INDEX {name} ON {table} ({column})"))
    return applied
