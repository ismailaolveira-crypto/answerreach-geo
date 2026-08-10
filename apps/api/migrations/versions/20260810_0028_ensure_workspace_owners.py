"""safely backfill eligible workspace owners without changing memberships

Revision ID: 20260810_0028
Revises: 20260810_0027
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0028"
down_revision: str | None = "20260810_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    missing = bind.execute(
        sa.text(
            """
            SELECT w.id AS workspace_id, w.company_id AS company_id
            FROM geo_workspaces_v1 AS w
            WHERE NOT EXISTS (
                SELECT 1
                FROM geo_workspace_memberships_v1 AS m
                WHERE m.workspace_id = w.id
                  AND m.status = 'active'
                  AND m.role = 'owner'
            )
            ORDER BY w.id
            """
        )
    ).mappings()
    for workspace in missing:
        candidate = bind.execute(
            sa.text(
                """
                SELECT u.id
                FROM users AS u
                WHERE u.company_id = :company_id
                  AND u.status = 'active'
                  AND u.role = 'company_admin'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM geo_workspace_memberships_v1 AS existing
                    WHERE existing.workspace_id = :workspace_id
                      AND existing.user_id = u.id
                  )
                ORDER BY u.id
                LIMIT 1
                """
            ),
            workspace,
        ).scalar_one_or_none()
        if candidate is None:
            # Existing viewer/reviewer/admin/revoked rows are explicit access
            # decisions, not owner candidates. Leave the workspace unchanged
            # when no unassociated company administrator is available.
            continue
        values = {
            "workspace_id": workspace["workspace_id"],
            "user_id": candidate,
        }
        bind.execute(
            sa.text(
                """
                INSERT INTO geo_workspace_memberships_v1
                    (workspace_id, user_id, role, status, joined_at, created_at, updated_at)
                VALUES
                    (:workspace_id, :user_id, 'owner', 'active', CURRENT_TIMESTAMP,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            values,
        )


def downgrade() -> None:
    # Ownership rows may have existed before this migration. Removing them would
    # be destructive, so the downgrade intentionally preserves access.
    pass
