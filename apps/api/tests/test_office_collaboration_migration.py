from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


API_ROOT = Path(__file__).resolve().parents[1]


def _alembic(database_path: Path, *args: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_office_connector_migration_preserves_existing_channel(tmp_path: Path) -> None:
    database_path = tmp_path / "office-connectors.db"
    _alembic(database_path, "upgrade", "20260827_0037")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, brand_aliases, status) VALUES (1, '测试企业', '[]', 'active')"
        )
        connection.execute(
            """
            INSERT INTO geo_workspaces_v1 (id, company_id, slug, brand_name, brand_aliases, status)
            VALUES (1, 1, 'office-migration', '测试品牌', '[]', 'active')
            """
        )
        connection.execute(
            """
            INSERT INTO geo_collaboration_channels_v1 (
                workspace_id, provider, status, display_name, configured_at, created_at, updated_at
            ) VALUES (1, 'wecom', 'configured', 'GEO 通知', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )

    _alembic(database_path, "upgrade", "20260830_0038")
    with sqlite3.connect(database_path) as connection:
        channel = connection.execute(
            """
            SELECT provider, status, display_name, connection_mode, configured_fields, capabilities
            FROM geo_collaboration_channels_v1
            """
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert channel == ("wecom", "configured", "GEO 通知", "webhook", "[]", "{}")
    assert {
        "geo_collaboration_member_bindings_v1",
        "geo_collaboration_notification_preferences_v1",
        "geo_collaboration_deliveries_v1",
    } <= tables
    assert integrity == "ok"
    assert version == "20260830_0038"
