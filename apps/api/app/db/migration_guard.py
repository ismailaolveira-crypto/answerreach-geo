"""Read-only Alembic revision guard for API startup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


API_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = API_ROOT / "migrations"
MIGRATION_COMMAND = "cd apps/api && uv run alembic upgrade head"


class DatabaseMigrationError(RuntimeError):
    """Raised when the database revision cannot safely run the current code."""


def code_migration_heads() -> tuple[str, ...]:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return tuple(sorted(ScriptDirectory.from_config(config).get_heads()))


def expected_migration_head() -> str:
    heads = code_migration_heads()
    if len(heads) != 1:
        raise DatabaseMigrationError(
            f"Code migration graph must have exactly one head; found {list(heads)!r}."
        )
    return heads[0]


def _sqlite_path(database: str | None) -> Path:
    if not database or database == ":memory:":
        raise DatabaseMigrationError(
            "API startup requires an Alembic-managed database file; "
            f"initialize it explicitly with `{MIGRATION_COMMAND}`."
        )
    path = Path(database).expanduser()
    return path.resolve() if path.is_absolute() else (API_ROOT / path).resolve()


def _sqlite_heads(database: str | None) -> tuple[str, ...]:
    path = _sqlite_path(database)
    if not path.is_file():
        raise DatabaseMigrationError(
            f"Database file does not exist at {path}; initialize it explicitly with "
            f"`{MIGRATION_COMMAND}`."
        )
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.Error as exc:
        raise DatabaseMigrationError(
            "Database has no readable Alembic revision; back it up, then run "
            f"`{MIGRATION_COMMAND}`."
        ) from exc
    finally:
        if connection is not None:
            connection.close()
    return tuple(sorted(str(row[0]) for row in rows if row and row[0]))


def _sqlalchemy_heads(database_url: str) -> tuple[str, ...]:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    except SQLAlchemyError as exc:
        raise DatabaseMigrationError(
            "Database has no readable Alembic revision; back it up, then run "
            f"`{MIGRATION_COMMAND}`."
        ) from exc
    finally:
        engine.dispose()
    return tuple(sorted(str(row[0]) for row in rows if row and row[0]))


def database_migration_heads(database_url: str) -> tuple[str, ...]:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return _sqlite_heads(url.database)
    return _sqlalchemy_heads(database_url)


def assert_database_at_head(database_url: str) -> str:
    expected = expected_migration_head()
    current = database_migration_heads(database_url)
    if current != (expected,):
        current_label = ", ".join(current) if current else "unversioned"
        raise DatabaseMigrationError(
            f"Database migration mismatch: current={current_label}, expected={expected}. "
            f"Back up the database, then run `{MIGRATION_COMMAND}`."
        )
    return expected


def main() -> None:
    head = assert_database_at_head(get_settings().database_url)
    print(f"database migration check: ok · {head}")


if __name__ == "__main__":
    main()
