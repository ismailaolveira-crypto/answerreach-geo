from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


API_ROOT = Path(__file__).resolve().parents[1]


def _alembic(database_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


def test_active_run_unique_migration_rejects_dirty_data_without_advancing(tmp_path: Path) -> None:
    database_path = tmp_path / "duplicate-active-runs.db"
    _alembic(database_path, "upgrade", "20260830_0041")
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO geo_agent_runs_v1 (workspace_id, action_id, status) VALUES (1, 7, ?)",
            [("queued",), ("running",)],
        )

    result = _alembic(database_path, "upgrade", "20260903_0042", check=False)

    assert result.returncode != 0
    assert "duplicate active Agent runs exist" in result.stderr
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        indexes = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("uq_geo_agent_run_active_action_v1",),
        ).fetchall()
    assert version == "20260830_0041"
    assert indexes == []


def test_active_run_unique_migration_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "active-run-round-trip.db"
    _alembic(database_path, "upgrade", "20260903_0042")
    _alembic(database_path, "downgrade", "20260830_0041")
    _alembic(database_path, "upgrade", "20260903_0042")

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("uq_geo_agent_run_active_action_v1",),
        ).fetchone()
    assert version == "20260903_0042"
    assert index is not None
    assert "WHERE status IN" in index[0]
