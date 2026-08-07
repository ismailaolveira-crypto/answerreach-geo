"""Add question library governance fields and review history.

Revision ID: 20260802_0016
Revises: 20260801_0015
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_0016"
down_revision = "20260801_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_question_plans_v1") as batch:
        batch.add_column(
            sa.Column("role", sa.String(length=60), nullable=False, server_default="technical_lead")
        )
        batch.add_column(sa.Column("topic_tags", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active")
        )
        batch.add_column(
            sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual")
        )
        batch.add_column(
            sa.Column("source_evidence", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.add_column(sa.Column("source_reason", sa.Text()))
        batch.add_column(sa.Column("source_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("cluster_id", sa.String(length=100)))
        batch.add_column(sa.Column("similar_question_id", sa.Integer()))
        batch.add_column(sa.Column("similarity", sa.Float()))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(
            sa.Column("template_variables", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column(
                "approved_by",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_geo_question_plans_approved_by_users"),
            )
        )
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("rejected_reason", sa.Text()))
        batch.create_index("ix_geo_question_plans_v1_role", ["role"])
        batch.create_index("ix_geo_question_plans_v1_status", ["status"])
        batch.create_index("ix_geo_question_plans_v1_cluster_id", ["cluster_id"])
        batch.create_index("ix_geo_question_plans_v1_similar_question_id", ["similar_question_id"])
        batch.create_index("ix_geo_question_plans_v1_approved_by", ["approved_by"])
    op.create_table(
        "geo_question_reviews_v1",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id", name="fk_geo_question_reviews_workspace"),
            nullable=False,
        ),
        sa.Column(
            "question_plan_id",
            sa.Integer(),
            sa.ForeignKey("geo_question_plans_v1.id", name="fk_geo_question_reviews_plan"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_geo_question_reviews_actor"),
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=32)),
        sa.Column("to_status", sa.String(length=32)),
        sa.Column("note", sa.Text()),
        sa.Column("snapshot", sa.JSON(), nullable=False),
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
    for name, columns in (
        ("ix_geo_question_reviews_v1_workspace_id", ["workspace_id"]),
        ("ix_geo_question_reviews_v1_question_plan_id", ["question_plan_id"]),
        ("ix_geo_question_reviews_v1_actor_user_id", ["actor_user_id"]),
    ):
        op.create_index(name, "geo_question_reviews_v1", columns)


def downgrade() -> None:
    op.drop_table("geo_question_reviews_v1")
    with op.batch_alter_table("geo_question_plans_v1") as batch:
        for name in (
            "ix_geo_question_plans_v1_approved_by",
            "ix_geo_question_plans_v1_cluster_id",
            "ix_geo_question_plans_v1_similar_question_id",
            "ix_geo_question_plans_v1_status",
            "ix_geo_question_plans_v1_role",
        ):
            batch.drop_index(name)
        for name in (
            "approved_by",
            "approved_at",
            "rejected_reason",
            "template_variables",
            "version",
            "similarity",
            "similar_question_id",
            "cluster_id",
            "source_at",
            "source_reason",
            "source_evidence",
            "source_type",
            "status",
            "topic_tags",
            "role",
        ):
            batch.drop_column(name)
