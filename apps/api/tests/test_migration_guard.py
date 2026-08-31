from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest

from app.core.config import Settings
from app.db.migration_guard import (
    DatabaseMigrationError,
    assert_database_at_head,
    code_migration_heads,
    expected_migration_head,
)


API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _database(path: Path, versions: list[str] | None) -> str:
    connection = sqlite3.connect(path)
    try:
        if versions is not None:
            connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.executemany(
                "INSERT INTO alembic_version (version_num) VALUES (?)",
                [(version,) for version in versions],
            )
            connection.commit()
    finally:
        connection.close()
    return f"sqlite:///{path}"


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def test_code_migration_graph_has_one_dynamic_head() -> None:
    head = expected_migration_head()
    assert code_migration_heads() == (head,)
    assert head.startswith("20")


def test_current_database_revision_passes_without_modifying_file(tmp_path: Path) -> None:
    path = tmp_path / "current.db"
    url = _database(path, [expected_migration_head()])
    before = _fingerprint(path)

    assert assert_database_at_head(url) == expected_migration_head()

    assert _fingerprint(path) == before


@pytest.mark.parametrize("versions", [None, [], ["20260809_0024"], ["a", "b"]])
def test_unready_database_fails_without_modifying_file(
    tmp_path: Path, versions: list[str] | None
) -> None:
    path = tmp_path / "unready.db"
    url = _database(path, versions)
    before = _fingerprint(path)

    with pytest.raises(DatabaseMigrationError, match="Alembic|migration mismatch"):
        assert_database_at_head(url)

    assert _fingerprint(path) == before


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"

    with pytest.raises(DatabaseMigrationError, match="does not exist"):
        assert_database_at_head(f"sqlite:///{path}")

    assert not path.exists()


def test_auto_create_tables_is_rejected() -> None:
    settings = Settings(_env_file=None, auto_create_tables=True)

    with pytest.raises(RuntimeError, match="no longer supported"):
        settings.validate_deployment()


def test_api_startup_has_no_runtime_schema_or_membership_backfill() -> None:
    source = (API_ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "create_all" not in source
    assert "backfill_legacy_workspace_memberships" not in source


def test_local_stack_checks_revision_before_starting_processes() -> None:
    source = (REPOSITORY_ROOT / "scripts/start-local.sh").read_text(encoding="utf-8")
    guard = source.index("python -m app.db.migration_guard")
    assert guard < source.index("pnpm run dev:api")
    assert guard < source.index("pnpm run dev:web")
    assert guard < source.index("pnpm run worker:queue")
