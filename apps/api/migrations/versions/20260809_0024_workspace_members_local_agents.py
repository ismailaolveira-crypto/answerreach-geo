"""Add workspace membership, invitations and Local Agent device status.

Revision ID: 20260809_0024
Revises: 20260808_0023
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260809_0024"
down_revision = "20260808_0023"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _create_table(name: str, *columns_and_constraints: object) -> None:
    """Support databases where development create_all already made 0024 tables."""

    if not _table_exists(name):
        op.create_table(name, *columns_and_constraints)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    _create_table(
        "geo_workspace_memberships_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("invited_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_geo_workspace_membership_user_v1"),
    )
    for column in ("workspace_id", "user_id", "role", "status"):
        _create_index(
            f"ix_geo_workspace_memberships_v1_{column}",
            "geo_workspace_memberships_v1",
            [column],
        )

    # Preserve today's company-wide visibility once, then make future access
    # explicit. New users are not automatically added to existing workspaces.
    op.execute(
        sa.text(
            """
            INSERT INTO geo_workspace_memberships_v1
                (workspace_id, user_id, role, status, joined_at, created_at, updated_at)
            SELECT
                w.id,
                u.id,
                CASE
                    WHEN u.role = 'company_admin' THEN 'owner'
                    WHEN u.role = 'content_operator' THEN 'operator'
                    WHEN u.role = 'reviewer' THEN 'reviewer'
                    ELSE 'viewer'
                END,
                'active',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM geo_workspaces_v1 AS w
            JOIN users AS u ON u.company_id = w.company_id
            WHERE u.status = 'active'
              AND NOT EXISTS (
                  SELECT 1
                  FROM geo_workspace_memberships_v1 AS existing
                  WHERE existing.workspace_id = w.id AND existing.user_id = u.id
              )
            """
        )
    )

    _create_table(
        "geo_workspace_invitations_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("invited_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("workspace_id", "email", "token_hash", "status", "invited_by_user_id"):
        _create_index(
            f"ix_geo_workspace_invitations_v1_{column}",
            "geo_workspace_invitations_v1",
            [column],
        )

    _create_table(
        "geo_local_agent_enrollments_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("workspace_id", "requested_by_user_id", "token_hash"):
        _create_index(
            f"ix_geo_local_agent_enrollments_v1_{column}",
            "geo_local_agent_enrollments_v1",
            [column],
        )

    _create_table(
        "geo_local_agent_nodes_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("geo_workspaces_v1.id"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(80), nullable=False),
        sa.Column("agent_version", sa.String(40), nullable=False),
        sa.Column("device_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("execution_mode", sa.String(32), nullable=False, server_default="status_only"),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("health", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("workspace_id", "owner_user_id", "device_token_hash", "status"):
        _create_index(
            f"ix_geo_local_agent_nodes_v1_{column}",
            "geo_local_agent_nodes_v1",
            [column],
        )


def downgrade() -> None:
    for table_name in (
        "geo_local_agent_nodes_v1",
        "geo_local_agent_enrollments_v1",
        "geo_workspace_invitations_v1",
        "geo_workspace_memberships_v1",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
