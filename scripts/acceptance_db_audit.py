#!/usr/bin/env python3
"""Read-only integrity and migration-head check for the live GEO database."""

from __future__ import annotations

import sqlite3
import os
import subprocess
import tempfile
from pathlib import Path


root = Path(__file__).resolve().parents[1]
database = root / "apps/api/geo_platform.db"
temporary_database: tempfile.TemporaryDirectory[str] | None = None
if not database.exists():
    temporary_database = tempfile.TemporaryDirectory(prefix="answerreach-db-audit-")
    database = Path(temporary_database.name) / "geo_platform.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "PYTHONPATH": str(root / "apps/api"),
        "UV_CACHE_DIR": str(root / ".uv-cache"),
    }
    subprocess.run(
        ["uv", "--directory", str(root / "apps/api"), "run", "alembic", "upgrade", "head"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
try:
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    active_run_index = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("uq_geo_agent_run_active_action_v1",),
    ).fetchone()
    active_fingerprint_index = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("uq_queue_job_active_fingerprint",),
    ).fetchone()
finally:
    connection.close()

if integrity != [("ok",)]:
    raise SystemExit(f"database integrity failed: {integrity!r}")
if foreign_keys:
    raise SystemExit(f"foreign key violations: {len(foreign_keys)}")
if version != ("20260904_0043",):
    raise SystemExit(f"unexpected migration version: {version!r}")
if active_run_index is None:
    raise SystemExit("required active Agent run index is missing")
if active_fingerprint_index is None:
    raise SystemExit("required active queue fingerprint index is missing")

source = "disposable migration" if temporary_database else "read-only local database"
print(f"database audit: ok · {version[0]} · {source}")
if temporary_database is not None:
    temporary_database.cleanup()
