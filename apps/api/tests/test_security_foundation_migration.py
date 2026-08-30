from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


API_ROOT = Path(__file__).resolve().parents[1]
TEST_AUTH_SECRET = "migration-test-auth-secret-with-at-least-32-characters"


def _alembic(database_path: Path, *args: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    environment["AUTH_SECRET"] = TEST_AUTH_SECRET
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_security_migration_preserves_data_and_encrypts_legacy_provider_key(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "security-foundation.db"
    legacy_key = "test-provider-key-must-not-remain-plaintext"
    _alembic(database_path, "upgrade", "20260830_0038")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO llm_providers (
                id, name, provider_type, api_base_url, model_name, auth_config,
                cost_rule, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                1,
                "迁移验证 Provider",
                "deepseek_web_search",
                "https://api.example.test",
                "test-model",
                json.dumps({"api_key": legacy_key}),
                "{}",
                "active",
            ),
        )

    _alembic(database_path, "upgrade", "20260830_0040")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        delivery_share_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(delivery_package_shares)"
            ).fetchall()
        }
        raw_auth_config = connection.execute(
            "SELECT auth_config FROM llm_providers WHERE id = 1"
        ).fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    auth_config = json.loads(raw_auth_config)
    assert {
        "auth_sessions",
        "security_rate_limits",
        "geo_collaboration_mentions_v1",
    } <= tables
    assert "credentials_version" in user_columns
    assert "confirmation_token_encrypted" in delivery_share_columns
    assert "api_key" not in auth_config
    assert auth_config["api_key_configured"] is True
    assert auth_config["api_key_encrypted"]
    assert legacy_key not in raw_auth_config
    assert integrity == "ok"
    assert version == "20260830_0040"
