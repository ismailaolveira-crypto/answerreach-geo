from __future__ import annotations

import json
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


def _seed_legacy_actions(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO companies (id, name, brand_aliases, status)
            VALUES (1, '测试企业', '[]', 'active')
            """
        )
        connection.execute(
            """
            INSERT INTO geo_workspaces_v1 (
                id, company_id, slug, brand_name, brand_aliases, status
            ) VALUES (1, 1, 'migration-test', '测试品牌', '[]', 'active')
            """
        )
        cases = [
            (1, "website_scope_gap", "website_recommendation", ["official_site"]),
            (2, "citation_gap", "article", ["zhihu", "csdn"]),
            (3, "schema_gap", "structured_data", ["official_site"]),
            (4, "source_gap", "third_party_source", ["industry_media"]),
            (5, "unknown", "custom_matrix", []),
        ]
        for opportunity_id, opportunity_type, asset_type, platforms in cases:
            connection.execute(
                """
                INSERT INTO geo_action_opportunities_v1 (
                    id, workspace_id, fingerprint, opportunity_type, title, summary,
                    priority_score, priority_label, evidence_strength,
                    recommended_asset_type, recommended_platforms, scope_snapshot,
                    rule_version, status
                ) VALUES (?, 1, ?, ?, ?, '摘要', 80, 'high', 1, ?, ?, ?,
                          'opportunity.v1', 'selected')
                """,
                (
                    opportunity_id,
                    f"{opportunity_id:064x}",
                    opportunity_type,
                    f"机会 {opportunity_id}",
                    asset_type,
                    json.dumps(platforms),
                    json.dumps({"batch_id": opportunity_id}),
                ),
            )
            connection.execute(
                """
                INSERT INTO geo_optimization_actions_v1 (
                    id, workspace_id, title, rationale, priority, status,
                    opportunity_id, stage, baseline_snapshot, selected_scope,
                    measurement_plan
                ) VALUES (?, 1, ?, '理由', 'high', 'proposed', ?, 'selected', '{}', '{}', '{}')
                """,
                (opportunity_id, f"行动 {opportunity_id}", opportunity_id),
            )


def test_action_execution_v2_migration_is_deterministic_and_non_lossy(tmp_path: Path) -> None:
    database_path = tmp_path / "action-execution-v2.db"
    _alembic(database_path, "upgrade", "20260824_0029")
    _seed_legacy_actions(database_path)

    _alembic(database_path, "upgrade", "20260824_0030")
    with sqlite3.connect(database_path) as connection:
        classifications = dict(
            connection.execute(
                "SELECT id, action_type FROM geo_optimization_actions_v1 ORDER BY id"
            ).fetchall()
        )
        action_count = connection.execute(
            "SELECT COUNT(*) FROM geo_optimization_actions_v1"
        ).fetchone()[0]
        target_count = connection.execute(
            "SELECT COUNT(*) FROM geo_action_targets_v1"
        ).fetchone()[0]
        target_shapes = connection.execute(
            """
            SELECT action_id, target_type, COALESCE(platform_key, ''), delivery_status
            FROM geo_action_targets_v1
            ORDER BY action_id, ordinal
            """
        ).fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert classifications == {
        1: "official_site",
        2: "article",
        3: "structured_data",
        4: "third_party_source",
        5: "legacy_unclassified",
    }
    assert action_count == 5
    assert target_count == 5
    assert target_shapes == [
        (1, "official_page", "", "gap_confirmed"),
        (2, "platform", "zhihu", "target_selected"),
        (2, "platform", "csdn", "target_selected"),
        (3, "schema", "", "schema_gap_confirmed"),
        (4, "external_source", "", "source_selected"),
    ]
    assert integrity == "ok"
    assert foreign_keys == []

    _alembic(database_path, "downgrade", "20260824_0029")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM geo_optimization_actions_v1"
        ).fetchone()[0] == 5
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    _alembic(database_path, "upgrade", "20260824_0030")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO geo_action_targets_v1 (
                workspace_id, action_id, target_key, target_type, display_name,
                target_ref, delivery_status, ordinal, metadata_json
            ) VALUES (1, 2, 'new:user-target', 'platform', '知乎', 'zhihu',
                      'target_selected', 99, '{}')
            """
        )
    refused = _alembic(
        database_path, "downgrade", "20260824_0029", check=False
    )
    assert refused.returncode != 0
    assert "Refusing lossy downgrade" in refused.stderr
