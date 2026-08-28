#!/usr/bin/env python3
"""Read-only integrity and migration-head check for the live GEO database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


database = Path(__file__).resolve().parents[1] / "apps/api/geo_platform.db"
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
if version != ("20260827_0037",):
    raise SystemExit(f"unexpected migration version: {version!r}")

print("database audit: ok · 20260827_0037")
