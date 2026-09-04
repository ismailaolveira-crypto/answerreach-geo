from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models.job import QueueJob


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


def test_active_fingerprint_migration_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "active-fingerprint-round-trip.db"
    _alembic(database_path, "upgrade", "20260904_0043")
    _alembic(database_path, "downgrade", "20260903_0042")
    _alembic(database_path, "upgrade", "20260904_0043")

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("uq_queue_job_active_fingerprint",),
        ).fetchone()
    assert version == "20260904_0043"
    assert index is not None
    assert "input_fingerprint" in index[0]


def test_active_fingerprint_index_compiles_without_sqlite_json_extract_on_postgresql() -> None:
    index = next(
        item
        for item in QueueJob.__table__.indexes
        if item.name == "uq_queue_job_active_fingerprint"
    )
    compiled = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "json_extract" not in compiled.lower()
    assert "payload_json ->>" in compiled
    assert "input_fingerprint" in compiled


def test_active_fingerprint_migration_rejects_dirty_data_without_advancing(tmp_path: Path) -> None:
    database_path = tmp_path / "duplicate-active-fingerprints.db"
    _alembic(database_path, "upgrade", "20260903_0042")
    payload = '{"workspace_id": 1, "input_fingerprint": "same-scope"}'
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO queue_jobs (
                job_type, status, priority, payload_json, attempts, max_attempts,
                created_at, updated_at
            ) VALUES (?, 'pending', 0, ?, 0, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            [("geo_opportunity.discover", payload), ("geo_opportunity.discover", payload)],
        )

    result = _alembic(database_path, "upgrade", "20260904_0043", check=False)

    assert result.returncode != 0
    assert "duplicate active queue fingerprints exist" in result.stderr
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        indexes = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("uq_queue_job_active_fingerprint",),
        ).fetchall()
        leftover = connection.execute("SELECT COUNT(*) FROM queue_jobs").fetchone()[0]
    assert version == "20260903_0042"
    assert indexes == []
    assert leftover == 2
