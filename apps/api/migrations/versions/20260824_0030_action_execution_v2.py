"""add typed action execution, evidence, approval, and target-level retest ledgers

Revision ID: 20260824_0030
Revises: 20260824_0029
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0030"
down_revision: str | None = "20260824_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACTION_TYPES = {
    "article",
    "official_site",
    "structured_data",
    "third_party_source",
    "legacy_unclassified",
}


def _json(value: object, fallback: object) -> object:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _canonical_fingerprint(value: object) -> str | None:
    if value in (None, {}, [], ""):
        return None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _classify_action(row: sa.RowMapping) -> tuple[str, str]:
    opportunity_type = str(row.get("opportunity_type") or "").strip().lower()
    recommended_asset_type = str(row.get("recommended_asset_type") or "").strip().lower()
    platforms = {
        str(value).strip().lower()
        for value in _json(row.get("recommended_platforms"), [])
        if str(value).strip()
    }

    if recommended_asset_type in {"structured_data", "schema", "json_ld", "json-ld"}:
        return "structured_data", "json_ld"
    if recommended_asset_type in {"third_party_source", "external_source"}:
        return "third_party_source", "external_public_content"
    if (
        opportunity_type in {"website_citation_readiness", "website_scope_gap"}
        or recommended_asset_type in {"website", "website_recommendation", "official_site"}
        or platforms == {"official_site"}
    ):
        return "official_site", "official_page_change"
    if recommended_asset_type == "article" or any(
        platform != "official_site" for platform in platforms
    ):
        return "article", "platform_article"
    return "legacy_unclassified", "legacy_deliverable"


def _target_status(row: sa.RowMapping) -> str:
    if (
        str(row.get("human_publish_status") or "") == "published"
        and str(row.get("publication_verification_status") or "")
        in {"verified", "publicly_verified"}
    ):
        return "publicly_verified"
    if str(row.get("draft_readback_status") or "") == "draft_saved":
        return "draft_saved"
    if row.get("candidate_draft_url"):
        return "draft_write_requested"
    return "target_selected"


def _target_defaults(
    action_type: str, platform_key: str, legacy_status: str = "target_selected"
) -> tuple[str, str | None, str, str]:
    if action_type == "official_site":
        status = (
            "same_domain_readback_verified"
            if legacy_status == "publicly_verified"
            else "gap_confirmed"
        )
        return "official_page", None, "官网", status
    if action_type == "structured_data":
        return "schema", None, "结构化数据", "schema_gap_confirmed"
    if action_type == "third_party_source":
        status = (
            "public_readback_verified"
            if legacy_status == "publicly_verified"
            else "source_selected"
        )
        return "external_source", None, platform_key or "第三方信源", status
    return "platform", platform_key or None, platform_key or "发布平台", legacy_status


def _backfill_actions_and_targets() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT a.id, a.workspace_id, a.question_plan_id, a.selected_scope,
                   a.opportunity_id, o.opportunity_type, o.recommended_asset_type,
                   o.recommended_platforms, o.scope_snapshot
            FROM geo_optimization_actions_v1 AS a
            LEFT JOIN geo_action_opportunities_v1 AS o ON o.id = a.opportunity_id
            ORDER BY a.id
            """
        )
    ).mappings()

    now = datetime.now(timezone.utc)
    for row in rows:
        action_type, deliverable_type = _classify_action(row)
        question_ids: list[int] = []
        if row.get("question_plan_id") is not None:
            question_ids.append(int(row["question_plan_id"]))
        evidence_questions = connection.execute(
            sa.text(
                """
                SELECT DISTINCT e.question_plan_id
                FROM geo_action_opportunity_evidence_v1 AS e
                WHERE e.opportunity_id = :opportunity_id
                ORDER BY e.question_plan_id
                """
            ),
            {"opportunity_id": row.get("opportunity_id")},
        ).scalars()
        question_ids = sorted({*question_ids, *(int(value) for value in evidence_questions)})
        model_keys = sorted(
            {
                str(value)
                for value in connection.execute(
                    sa.text(
                        """
                        SELECT DISTINCT e.model_key
                        FROM geo_action_opportunity_evidence_v1 AS e
                        WHERE e.opportunity_id = :opportunity_id AND e.model_key IS NOT NULL
                        ORDER BY e.model_key
                        """
                    ),
                    {"opportunity_id": row.get("opportunity_id")},
                ).scalars()
                if str(value).strip()
            }
        )
        selected_scope = _json(row.get("selected_scope"), {})
        if not selected_scope:
            selected_scope = _json(row.get("scope_snapshot"), {})
        scope_fingerprint = _canonical_fingerprint(selected_scope)
        connection.execute(
            sa.text(
                """
                UPDATE geo_optimization_actions_v1
                SET action_type = :action_type,
                    deliverable_type = :deliverable_type,
                    workflow_version = 'action-flow.legacy-v1',
                    affected_question_ids = :question_ids,
                    affected_model_keys = :model_keys,
                    scope_fingerprint = :scope_fingerprint,
                    measurement_status = 'not_eligible'
                WHERE id = :action_id
                """
            ),
            {
                "action_type": action_type,
                "deliverable_type": deliverable_type,
                "question_ids": json.dumps(question_ids, ensure_ascii=False),
                "model_keys": json.dumps(model_keys, ensure_ascii=False),
                "scope_fingerprint": scope_fingerprint,
                "action_id": row["id"],
            },
        )

        distribution_targets = connection.execute(
            sa.text(
                """
                SELECT dt.id, dt.platform_key, dt.draft_readback_status,
                       dt.candidate_draft_url, dt.draft_url, dt.public_url,
                       dt.human_publish_status, dt.publication_verification_status,
                       dt.published_at, dt.published_by_user_id, dr.id AS distribution_run_id
                FROM geo_distribution_targets_v1 AS dt
                JOIN geo_distribution_runs_v1 AS dr ON dr.id = dt.distribution_run_id
                WHERE dr.action_id = :action_id
                ORDER BY dt.id
                """
            ),
            {"action_id": row["id"]},
        ).mappings().all()
        seen_platforms: set[str] = set()
        ordinal = 0
        for target in distribution_targets:
            platform_key = str(target.get("platform_key") or "").strip().lower()
            if platform_key:
                seen_platforms.add(platform_key)
            target_ref = (
                target.get("public_url")
                or target.get("draft_url")
                or target.get("candidate_draft_url")
                or platform_key
                or f"distribution-target:{target['id']}"
            )
            legacy_status = _target_status(target)
            target_type, stored_platform_key, display_name, status = _target_defaults(
                action_type, platform_key, legacy_status
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO geo_action_targets_v1 (
                        workspace_id, action_id, target_key, target_type, platform_key,
                        display_name, target_ref, delivery_status, ordinal, metadata_json,
                        completed_at, completed_by_user_id, verified_at, created_at, updated_at
                    ) VALUES (
                        :workspace_id, :action_id, :target_key, :target_type, :platform_key,
                        :display_name, :target_ref, :delivery_status, :ordinal, :metadata_json,
                        :completed_at, :completed_by_user_id, :verified_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "workspace_id": row["workspace_id"],
                    "action_id": row["id"],
                    "target_key": f"legacy-distribution:{target['id']}",
                    "target_type": target_type,
                    "platform_key": stored_platform_key,
                    "display_name": display_name,
                    "target_ref": str(target_ref),
                    "delivery_status": status,
                    "ordinal": ordinal,
                    "metadata_json": json.dumps(
                        {
                            "migration_source": "geo_distribution_targets_v1",
                            "distribution_target_id": target["id"],
                            "distribution_run_id": target["distribution_run_id"],
                        },
                        ensure_ascii=False,
                    ),
                    "completed_at": (
                        target.get("published_at") if legacy_status == "publicly_verified" else None
                    ),
                    "completed_by_user_id": (
                        target.get("published_by_user_id")
                        if legacy_status == "publicly_verified"
                        else None
                    ),
                    "verified_at": (
                        target.get("published_at") if legacy_status == "publicly_verified" else None
                    ),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            ordinal += 1

        recommended_platforms = [
            str(value).strip().lower()
            for value in _json(row.get("recommended_platforms"), [])
            if str(value).strip()
        ]
        for platform_key in recommended_platforms:
            if platform_key in seen_platforms:
                continue
            target_type, stored_platform_key, display_name, initial_status = _target_defaults(
                action_type, platform_key
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO geo_action_targets_v1 (
                        workspace_id, action_id, target_key, target_type, platform_key,
                        display_name, target_ref, delivery_status, ordinal, metadata_json,
                        created_at, updated_at
                    ) VALUES (
                        :workspace_id, :action_id, :target_key, :target_type, :platform_key,
                        :display_name, :target_ref, :delivery_status, :ordinal, :metadata_json,
                        :created_at, :updated_at
                    )
                    """
                ),
                {
                    "workspace_id": row["workspace_id"],
                    "action_id": row["id"],
                    "target_key": f"legacy-opportunity:{platform_key}",
                    "target_type": target_type,
                    "platform_key": stored_platform_key,
                    "display_name": display_name,
                    "target_ref": platform_key,
                    "delivery_status": initial_status,
                    "ordinal": ordinal,
                    "metadata_json": json.dumps(
                        {
                            "migration_source": "geo_action_opportunities_v1",
                            "opportunity_id": row.get("opportunity_id"),
                        },
                        ensure_ascii=False,
                    ),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            ordinal += 1


def upgrade() -> None:
    with op.batch_alter_table("geo_optimization_actions_v1") as batch:
        batch.add_column(
            sa.Column(
                "action_type",
                sa.String(40),
                nullable=False,
                server_default="legacy_unclassified",
            )
        )
        batch.add_column(
            sa.Column(
                "deliverable_type",
                sa.String(60),
                nullable=False,
                server_default="legacy_deliverable",
            )
        )
        batch.add_column(
            sa.Column(
                "workflow_version",
                sa.String(40),
                nullable=False,
                server_default="action-flow.legacy-v1",
            )
        )
        batch.add_column(sa.Column("assignee_user_id", sa.Integer()))
        batch.add_column(sa.Column("due_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("approval_due_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("approval_requested_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("blocked_reason_code", sa.String(80)))
        batch.add_column(sa.Column("blocked_note", sa.Text()))
        batch.add_column(
            sa.Column("affected_question_ids", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("affected_model_keys", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("scope_fingerprint", sa.String(64)))
        batch.add_column(
            sa.Column(
                "measurement_status",
                sa.String(32),
                nullable=False,
                server_default="not_eligible",
            )
        )
        batch.create_foreign_key(
            "fk_geo_action_assignee_user_v2", "users", ["assignee_user_id"], ["id"]
        )
        for column in (
            "action_type",
            "assignee_user_id",
            "due_at",
            "approval_due_at",
            "blocked_reason_code",
            "scope_fingerprint",
            "measurement_status",
        ):
            batch.create_index(f"ix_geo_optimization_actions_v1_{column}", [column])

    op.create_table(
        "geo_action_targets_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id"), nullable=False),
        sa.Column("target_key", sa.String(160), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("platform_key", sa.String(80)),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("target_ref", sa.String(1500), nullable=False),
        sa.Column("delivery_status", sa.String(50), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("action_id", "target_key", name="uq_geo_action_target_key_v1"),
    )
    for column in (
        "workspace_id", "action_id", "target_type", "platform_key", "delivery_status",
        "completed_by_user_id", "verified_at",
    ):
        op.create_index(f"ix_geo_action_targets_v1_{column}", "geo_action_targets_v1", [column])

    op.create_table(
        "geo_action_completion_evidence_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("geo_action_targets_v1.id"), nullable=False),
        sa.Column("evidence_type", sa.String(50), nullable=False),
        sa.Column("source_url", sa.String(1500)),
        sa.Column("artifact_uri", sa.String(1500)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("submitted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes_evidence_id", sa.Integer(), sa.ForeignKey("geo_action_completion_evidence_v1.id"), unique=True),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_geo_action_evidence_idempotency_v1"),
    )
    for column in (
        "workspace_id", "action_id", "target_id", "evidence_type", "sha256",
        "verification_status", "submitted_by_user_id", "verified_by_user_id", "supersedes_evidence_id",
    ):
        op.create_index(
            f"ix_geo_action_completion_evidence_v1_{column}",
            "geo_action_completion_evidence_v1",
            [column],
        )

    op.create_table(
        "geo_action_approvals_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("geo_optimization_actions_v1.id"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("geo_action_targets_v1.id")),
        sa.Column("approval_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.Column("subject_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "action_id", "target_id", "approval_type", "version",
            name="uq_geo_action_approval_version_v1",
        ),
    )
    for column in (
        "workspace_id", "action_id", "target_id", "approval_type", "status",
        "requested_by_user_id", "reviewer_user_id", "due_at", "subject_fingerprint",
    ):
        op.create_index(f"ix_geo_action_approvals_v1_{column}", "geo_action_approvals_v1", [column])

    op.create_table(
        "geo_reobservation_targets_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("reobservation_id", sa.Integer(), sa.ForeignKey("geo_reobservations_v1.id"), nullable=False),
        sa.Column("action_target_id", sa.Integer(), sa.ForeignKey("geo_action_targets_v1.id"), nullable=False),
        sa.Column("completion_evidence_id", sa.Integer(), sa.ForeignKey("geo_action_completion_evidence_v1.id"), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("reobservation_id", "action_target_id", name="uq_geo_reobservation_target_v1"),
    )
    for column in (
        "workspace_id", "reobservation_id", "action_target_id", "completion_evidence_id", "scope_fingerprint",
    ):
        op.create_index(
            f"ix_geo_reobservation_targets_v1_{column}", "geo_reobservation_targets_v1", [column]
        )

    _backfill_actions_and_targets()


def downgrade() -> None:
    connection = op.get_bind()
    unsafe_counts = {
        "completion evidence": connection.execute(
            sa.text("SELECT COUNT(*) FROM geo_action_completion_evidence_v1")
        ).scalar_one(),
        "approvals": connection.execute(
            sa.text("SELECT COUNT(*) FROM geo_action_approvals_v1")
        ).scalar_one(),
        "reobservation target links": connection.execute(
            sa.text("SELECT COUNT(*) FROM geo_reobservation_targets_v1")
        ).scalar_one(),
        "non-migrated targets": connection.execute(
            sa.text(
                """
                SELECT COUNT(*) FROM geo_action_targets_v1
                WHERE json_extract(metadata_json, '$.migration_source') IS NULL
                """
            )
        ).scalar_one(),
    }
    unsafe = {label: count for label, count in unsafe_counts.items() if int(count or 0) > 0}
    if unsafe:
        detail = ", ".join(f"{label}={count}" for label, count in unsafe.items())
        raise RuntimeError(
            "Refusing lossy downgrade of action execution v2; export the new ledger first: " + detail
        )

    op.drop_table("geo_reobservation_targets_v1")
    op.drop_table("geo_action_approvals_v1")
    op.drop_table("geo_action_completion_evidence_v1")
    op.drop_table("geo_action_targets_v1")

    with op.batch_alter_table("geo_optimization_actions_v1") as batch:
        for column in (
            "measurement_status",
            "scope_fingerprint",
            "blocked_reason_code",
            "approval_due_at",
            "due_at",
            "assignee_user_id",
            "action_type",
        ):
            batch.drop_index(f"ix_geo_optimization_actions_v1_{column}")
        batch.drop_constraint("fk_geo_action_assignee_user_v2", type_="foreignkey")
        for column in (
            "measurement_status",
            "scope_fingerprint",
            "affected_model_keys",
            "affected_question_ids",
            "blocked_note",
            "blocked_reason_code",
            "approval_requested_at",
            "approval_due_at",
            "due_at",
            "assignee_user_id",
            "workflow_version",
            "deliverable_type",
            "action_type",
        ):
            batch.drop_column(column)
