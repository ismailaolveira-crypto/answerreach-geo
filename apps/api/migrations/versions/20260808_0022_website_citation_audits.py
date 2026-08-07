"""Add persisted website citation-readiness audits.

Revision ID: 20260808_0022
Revises: 20260808_0021
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0022"
down_revision = "20260808_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_website_audits_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id"),
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("requested_url", sa.String(1500), nullable=False),
        sa.Column("final_url", sa.String(1500)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("content_type", sa.String(255)),
        sa.Column("title", sa.String(1000)),
        sa.Column("meta_description", sa.Text()),
        sa.Column("canonical_url", sa.String(1500)),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("audit_version", sa.String(80), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("findings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("response_headers", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_html", sa.Text()),
        sa.Column("raw_html_sha256", sa.String(64)),
        sa.Column("raw_html_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovery_documents", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("artifact_manifest", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("response_ms", sa.Integer()),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index("ix_geo_website_audits_v1_workspace_id", "geo_website_audits_v1", ["workspace_id"])
    op.create_index(
        "ix_geo_website_audits_v1_requested_by_user_id",
        "geo_website_audits_v1",
        ["requested_by_user_id"],
    )
    op.create_index("ix_geo_website_audits_v1_status", "geo_website_audits_v1", ["status"])
    op.create_index(
        "ix_geo_website_audits_v1_raw_html_sha256",
        "geo_website_audits_v1",
        ["raw_html_sha256"],
    )
    op.create_index(
        "ix_geo_website_audits_v1_checked_at",
        "geo_website_audits_v1",
        ["checked_at"],
    )


def downgrade() -> None:
    op.drop_table("geo_website_audits_v1")
