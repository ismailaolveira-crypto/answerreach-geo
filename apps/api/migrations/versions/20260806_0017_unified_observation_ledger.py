"""Add a canonical batch and observation-task ledger.

Revision ID: 20260806_0017
Revises: 20260802_0016
"""

from __future__ import annotations

import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260806_0017"
down_revision = "20260802_0016"
branch_labels = None
depends_on = None


def _payload(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def upgrade() -> None:
    op.create_table(
        "geo_observation_batches_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id"),
            nullable=False,
        ),
        sa.Column("queue_job_id", sa.Integer(), sa.ForeignKey("queue_jobs.id"), unique=True),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_count", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("total_tasks", sa.Integer(), nullable=False),
        sa.Column("completed_tasks", sa.Integer(), nullable=False),
        sa.Column("failed_tasks", sa.Integer(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    for column in ("workspace_id", "queue_job_id", "requested_by_user_id", "status"):
        op.create_index(
            f"ix_geo_observation_batches_v1_{column}",
            "geo_observation_batches_v1",
            [column],
        )

    op.create_table(
        "geo_observation_tasks_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("geo_observation_batches_v1.id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id"),
            nullable=False,
        ),
        sa.Column("queue_job_id", sa.Integer(), sa.ForeignKey("queue_jobs.id"), unique=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_observation_runs_v1.id")),
        sa.Column(
            "evidence_id",
            sa.Integer(),
            sa.ForeignKey("geo_evidence_v1.id"),
            unique=True,
        ),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("llm_providers.id")),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("provider_label", sa.String(length=160), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("model_label", sa.String(length=160), nullable=False),
        sa.Column(
            "question_plan_id",
            sa.Integer(),
            sa.ForeignKey("geo_question_plans_v1.id"),
            nullable=False,
        ),
        sa.Column("question_text_snapshot", sa.Text(), nullable=False),
        sa.Column("sample_key", sa.String(length=160), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("observation_group_id", sa.String(length=160)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "batch_id",
            "sample_key",
            name="uq_geo_observation_task_matrix_v1",
        ),
    )
    for column in (
        "batch_id",
        "workspace_id",
        "queue_job_id",
        "run_id",
        "evidence_id",
        "provider_id",
        "model_key",
        "question_plan_id",
        "observation_group_id",
        "status",
    ):
        op.create_index(
            f"ix_geo_observation_tasks_v1_{column}",
            "geo_observation_tasks_v1",
            [column],
        )

    op.create_index(
        "ix_geo_evidence_v1_workspace_captured",
        "geo_evidence_v1",
        ["workspace_id", "captured_at"],
    )
    op.create_index(
        "ix_geo_evidence_v1_workspace_question_model_captured",
        "geo_evidence_v1",
        ["workspace_id", "question_plan_id", "model_key", "captured_at"],
    )
    op.create_index(
        "ix_geo_evidence_v1_workspace_real_captured",
        "geo_evidence_v1",
        ["workspace_id", "is_real_provider_evidence", "captured_at"],
    )

    with op.batch_alter_table("geo_sampling_batches_v1") as batch:
        batch.add_column(sa.Column("observation_ledger_batch_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_geo_sampling_batch_observation_ledger_v1",
            "geo_observation_batches_v1",
            ["observation_ledger_batch_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_geo_sampling_batch_observation_ledger_v1",
            ["observation_ledger_batch_id"],
        )
    op.create_index(
        "ix_geo_sampling_batches_v1_observation_ledger_batch_id",
        "geo_sampling_batches_v1",
        ["observation_ledger_batch_id"],
    )

    with op.batch_alter_table("geo_sampling_samples_v1") as batch:
        batch.add_column(sa.Column("observation_task_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_geo_sampling_sample_observation_task_v1",
            "geo_observation_tasks_v1",
            ["observation_task_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_geo_sampling_sample_observation_task_v1",
            ["observation_task_id"],
        )
    op.create_index(
        "ix_geo_sampling_samples_v1_observation_task_id",
        "geo_sampling_samples_v1",
        ["observation_task_id"],
    )

    _backfill_existing_observations()


def _backfill_existing_observations() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    batches = sa.Table("geo_observation_batches_v1", metadata, autoload_with=bind)
    tasks = sa.Table("geo_observation_tasks_v1", metadata, autoload_with=bind)

    evidence_rows = {
        int(row["id"]): row
        for row in bind.execute(
            sa.text(
                "SELECT e.*, q.question_text FROM geo_evidence_v1 e "
                "JOIN geo_question_plans_v1 q ON q.id = e.question_plan_id"
            )
        ).mappings()
    }
    linked_evidence_ids: set[int] = set()
    batch_ids_by_queue_job: dict[int, int] = {}

    queue_batches = bind.execute(
        sa.text(
            "SELECT id, status, payload_json, started_at, finished_at, created_at, updated_at "
            "FROM queue_jobs WHERE job_type = 'geo_observation.batch' ORDER BY id"
        )
    ).mappings()
    for row in queue_batches:
        data = _payload(row["payload_json"])
        result = bind.execute(
            batches.insert().values(
                workspace_id=_as_int(data.get("workspace_id")),
                queue_job_id=int(row["id"]),
                requested_by_user_id=_as_int(data.get("actor_user_id")) or None,
                source_type="official_api",
                status=str(row["status"] or "pending"),
                provider_count=_as_int(data.get("provider_count")),
                question_count=_as_int(data.get("question_count")),
                repeat_count=max(1, _as_int(data.get("repeat_count"), 1)),
                total_tasks=_as_int(data.get("total")),
                completed_tasks=0,
                failed_tasks=0,
                configuration={
                    "schema": "unified-observation-ledger/v1",
                    "providers": data.get("providers") or [],
                    "questions": data.get("questions") or [],
                    "migrated_from": "queue_jobs",
                },
                started_at=_as_datetime(row["started_at"]),
                completed_at=_as_datetime(row["finished_at"]),
                created_at=_as_datetime(row["created_at"]),
                updated_at=_as_datetime(row["updated_at"]),
            )
        )
        batch_ids_by_queue_job[int(row["id"])] = int(result.inserted_primary_key[0])

    queue_tasks = bind.execute(
        sa.text(
            "SELECT id, status, attempts, payload_json, error_message, started_at, "
            "finished_at, created_at, updated_at FROM queue_jobs "
            "WHERE job_type = 'geo_observation.collect' ORDER BY id"
        )
    ).mappings()
    counts_by_batch: dict[int, dict[str, int]] = {}
    for row in queue_tasks:
        data = _payload(row["payload_json"])
        ledger_batch_id = batch_ids_by_queue_job.get(_as_int(data.get("observation_batch_id")))
        if ledger_batch_id is None:
            continue
        evidence_id = _as_int(data.get("evidence_id")) or None
        evidence = evidence_rows.get(evidence_id or 0)
        model_key = str(data.get("provider_key") or (evidence and evidence["model_key"]) or "unknown")
        model_label = str(
            data.get("provider_label") or (evidence and evidence["model_label"]) or model_key
        )
        status = "completed" if row["status"] == "success" else str(row["status"])
        bind.execute(
            tasks.insert().values(
                batch_id=ledger_batch_id,
                workspace_id=_as_int(data.get("workspace_id")),
                queue_job_id=int(row["id"]),
                run_id=_as_int(data.get("run_id")) or (int(evidence["run_id"]) if evidence else None),
                evidence_id=evidence_id,
                provider_id=_as_int(data.get("provider_id")) or None,
                provider_key=str(data.get("provider_key") or "unknown"),
                provider_label=str(data.get("provider_label") or model_label),
                model_key=model_key,
                model_label=model_label,
                question_plan_id=_as_int(data.get("question_plan_id")),
                question_text_snapshot=str(
                    data.get("question_label") or (evidence and evidence["question_text"]) or ""
                ),
                sample_key=f"queue-job:{int(row['id'])}",
                repeat_index=max(1, _as_int(data.get("repeat_index"), 1)),
                repeat_count=max(1, _as_int(data.get("repeat_count"), 1)),
                observation_group_id=data.get("observation_group_id"),
                status=status,
                attempt_count=_as_int(row["attempts"]),
                error_detail=row["error_message"],
                started_at=_as_datetime(row["started_at"]),
                completed_at=_as_datetime(row["finished_at"]),
                created_at=_as_datetime(row["created_at"]),
                updated_at=_as_datetime(row["updated_at"]),
            )
        )
        if evidence_id is not None:
            linked_evidence_ids.add(evidence_id)
        totals = counts_by_batch.setdefault(ledger_batch_id, {"completed": 0, "failed": 0})
        totals["completed"] += int(status == "completed")
        totals["failed"] += int(status == "failed")

    for batch_id, totals in counts_by_batch.items():
        bind.execute(
            batches.update()
            .where(batches.c.id == batch_id)
            .values(completed_tasks=totals["completed"], failed_tasks=totals["failed"])
        )

    # Older browser/imported evidence predates the queue matrix. Preserve every
    # sample as its own one-task imported batch rather than inventing grouping.
    for evidence_id, evidence in evidence_rows.items():
        if evidence_id in linked_evidence_ids:
            continue
        environment = _payload(evidence["sampling_environment"])
        captured_at = _as_datetime(evidence["captured_at"])
        result = bind.execute(
            batches.insert().values(
                workspace_id=int(evidence["workspace_id"]),
                source_type="legacy_import",
                status="completed",
                provider_count=1,
                question_count=1,
                repeat_count=max(1, _as_int(environment.get("repeat_count"), 1)),
                total_tasks=1,
                completed_tasks=1,
                failed_tasks=0,
                configuration={
                    "schema": "unified-observation-ledger/v1",
                    "migrated_from": str(evidence["evidence_kind"]),
                },
                started_at=captured_at,
                completed_at=captured_at,
                created_at=_as_datetime(evidence["created_at"]),
                updated_at=_as_datetime(evidence["updated_at"]),
            )
        )
        batch_id = int(result.inserted_primary_key[0])
        bind.execute(
            tasks.insert().values(
                batch_id=batch_id,
                workspace_id=int(evidence["workspace_id"]),
                run_id=int(evidence["run_id"]),
                evidence_id=evidence_id,
                provider_id=_as_int(environment.get("provider_id")) or None,
                provider_key=str(environment.get("provider_type") or evidence["model_key"]),
                provider_label=str(evidence["model_label"]),
                model_key=str(evidence["model_key"]),
                model_label=str(evidence["model_label"]),
                question_plan_id=int(evidence["question_plan_id"]),
                question_text_snapshot=str(evidence["question_text"]),
                sample_key=f"evidence:{evidence_id}",
                repeat_index=max(1, _as_int(environment.get("repeat_index"), 1)),
                repeat_count=max(1, _as_int(environment.get("repeat_count"), 1)),
                observation_group_id=environment.get("observation_group_id"),
                status="completed",
                attempt_count=1,
                started_at=captured_at,
                completed_at=captured_at,
                created_at=_as_datetime(evidence["created_at"]),
                updated_at=_as_datetime(evidence["updated_at"]),
            )
        )

    # Existing browser samples already point at evidence. Reuse that durable
    # evidence link to attach them to the canonical task created above.
    bind.execute(
        sa.text(
            "UPDATE geo_sampling_samples_v1 "
            "SET observation_task_id = ("
            "SELECT t.id FROM geo_observation_tasks_v1 t "
            "WHERE t.evidence_id = geo_sampling_samples_v1.evidence_id"
            ") WHERE evidence_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_sampling_samples_v1_observation_task_id",
        table_name="geo_sampling_samples_v1",
    )
    with op.batch_alter_table("geo_sampling_samples_v1") as batch:
        batch.drop_constraint("uq_geo_sampling_sample_observation_task_v1", type_="unique")
        batch.drop_constraint("fk_geo_sampling_sample_observation_task_v1", type_="foreignkey")
        batch.drop_column("observation_task_id")
    op.drop_index(
        "ix_geo_sampling_batches_v1_observation_ledger_batch_id",
        table_name="geo_sampling_batches_v1",
    )
    with op.batch_alter_table("geo_sampling_batches_v1") as batch:
        batch.drop_constraint("uq_geo_sampling_batch_observation_ledger_v1", type_="unique")
        batch.drop_constraint("fk_geo_sampling_batch_observation_ledger_v1", type_="foreignkey")
        batch.drop_column("observation_ledger_batch_id")
    for index_name in (
        "ix_geo_evidence_v1_workspace_real_captured",
        "ix_geo_evidence_v1_workspace_question_model_captured",
        "ix_geo_evidence_v1_workspace_captured",
    ):
        op.drop_index(index_name, table_name="geo_evidence_v1")
    op.drop_table("geo_observation_tasks_v1")
    op.drop_table("geo_observation_batches_v1")
