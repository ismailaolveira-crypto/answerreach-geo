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
finally:
    connection.close()

if integrity != [("ok",)]:
    raise SystemExit(f"database integrity failed: {integrity!r}")
if foreign_keys:
    raise SystemExit(f"foreign key violations: {len(foreign_keys)}")
supported_versions = {("20260903_0042",)}
if temporary_database is None:
    supported_versions.add(("20260830_0041",))
if version not in supported_versions:
    raise SystemExit(f"unexpected migration version: {version!r}")

source = "disposable migration" if temporary_database else "read-only local database"
print(f"database audit: ok · {version[0]} · {source}")
if temporary_database is not None:
    temporary_database.cleanup()
