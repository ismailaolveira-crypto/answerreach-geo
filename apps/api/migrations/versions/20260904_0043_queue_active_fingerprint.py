"""Prevent concurrent duplicate Agent jobs for the same fingerprint.

Revision ID: 20260904_0043
Revises: 20260903_0042
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0043"
down_revision = "20260903_0042"
branch_labels = None
depends_on = None


ACTIVE_FINGERPRINT_PREDICATE_SQLITE = (
    "status IN ('pending', 'running', 'recovering') "
    "AND json_extract(payload_json, '$.input_fingerprint') IS NOT NULL "
    "AND json_extract(payload_json, '$.input_fingerprint') != ''"
)
ACTIVE_FINGERPRINT_PREDICATE_PG = (
    "status IN ('pending', 'running', 'recovering') "
    "AND COALESCE(payload_json->>'input_fingerprint', '') <> ''"
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        workspace_expr = "payload_json->>'workspace_id'"
        fingerprint_expr = "payload_json->>'input_fingerprint'"
        predicate = ACTIVE_FINGERPRINT_PREDICATE_PG
    else:
        workspace_expr = "json_extract(payload_json, '$.workspace_id')"
        fingerprint_expr = "json_extract(payload_json, '$.input_fingerprint')"
        predicate = ACTIVE_FINGERPRINT_PREDICATE_SQLITE
    duplicates = bind.execute(
        sa.text(
            f"""
            SELECT job_type, {workspace_expr}, {fingerprint_expr}, COUNT(*) AS active_count
            FROM queue_jobs
            WHERE {predicate}
            GROUP BY job_type, {workspace_expr}, {fingerprint_expr}
            HAVING COUNT(*) > 1
            LIMIT 10
            """
        )
    ).fetchall()
    if duplicates:
        sample = ", ".join(
            f"job_type={row[0]!r} workspace_id={row[1]!r} fingerprint={row[2]!r} count={row[3]}"
            for row in duplicates
        )
        raise RuntimeError(
            "Cannot create uq_queue_job_active_fingerprint: duplicate active queue "
            "fingerprints exist; resolve them before retrying the migration "
            f"({sample})"
        )
    if dialect == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX uq_queue_job_active_fingerprint
                ON queue_jobs (
                    job_type,
                    (payload_json->>'workspace_id'),
                    (payload_json->>'input_fingerprint')
                )
                WHERE status IN ('pending', 'running', 'recovering')
                  AND COALESCE(payload_json->>'input_fingerprint', '') <> ''
                """
            )
        )
        return
    op.create_index(
        "uq_queue_job_active_fingerprint",
        "queue_jobs",
        [
            "job_type",
            sa.text("json_extract(payload_json, '$.workspace_id')"),
            sa.text("json_extract(payload_json, '$.input_fingerprint')"),
        ],
        unique=True,
        sqlite_where=sa.text(ACTIVE_FINGERPRINT_PREDICATE_SQLITE),
    )


def downgrade() -> None:
    op.drop_index("uq_queue_job_active_fingerprint", table_name="queue_jobs")
