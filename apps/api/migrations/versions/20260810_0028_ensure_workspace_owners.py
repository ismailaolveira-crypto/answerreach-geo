"""ensure every existing workspace has an explicit owner

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
                LEFT JOIN geo_workspace_memberships_v1 AS m
                  ON m.user_id = u.id AND m.workspace_id = :workspace_id
                WHERE u.status = 'active'
                  AND (
                    (m.status = 'active')
                    OR u.company_id = :company_id
                    OR u.role = 'super_admin'
                  )
                ORDER BY
                  CASE WHEN m.status = 'active' THEN 0 ELSE 1 END,
                  CASE u.role WHEN 'company_admin' THEN 0 WHEN 'super_admin' THEN 1 ELSE 2 END,
                  u.id
                LIMIT 1
                """
            ),
            workspace,
        ).scalar_one_or_none()
        if candidate is None:
            raise RuntimeError(
                f"Workspace {workspace['workspace_id']} has no active user who can become owner"
            )
        existing = bind.execute(
            sa.text(
                """
                SELECT id FROM geo_workspace_memberships_v1
                WHERE workspace_id = :workspace_id AND user_id = :user_id
                """
            ),
            {"workspace_id": workspace["workspace_id"], "user_id": candidate},
        ).scalar_one_or_none()
        values = {
            "workspace_id": workspace["workspace_id"],
            "user_id": candidate,
        }
        if existing is None:
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
        else:
            bind.execute(
                sa.text(
                    """
                    UPDATE geo_workspace_memberships_v1
                    SET role = 'owner', status = 'active', revoked_at = NULL,
                        joined_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :membership_id
                    """
                ),
                {"membership_id": existing},
            )


def downgrade() -> None:
    # Ownership rows may have existed before this migration. Removing them would
    # be destructive, so the downgrade intentionally preserves access.
    pass
