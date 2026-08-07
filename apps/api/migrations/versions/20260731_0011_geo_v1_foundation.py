"""Add the durable Spring Yuan GEO V1 operating loop.

Revision ID: 20260731_0011
Revises: 20260713_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0011"
down_revision = "20260713_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("target_questions") as batch:
        batch.add_column(sa.Column("journey_stage", sa.String(length=50), nullable=False, server_default="consideration"))
        batch.add_column(sa.Column("contains_brand", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("counts_for_visibility", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("variants", sa.JSON(), nullable=False, server_default="[]"))
        batch.create_index("ix_target_questions_journey_stage", ["journey_stage"])
        batch.create_index("ix_target_questions_contains_brand", ["contains_brand"])
        batch.create_index("ix_target_questions_counts_for_visibility", ["counts_for_visibility"])

    op.create_table(
        "brand_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False, server_default="product"),
        sa.Column("source_url", sa.String(length=1000)),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("owner", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_brand_claims_project_id", "brand_claims", ["project_id"])
    op.create_index("ix_brand_claims_status", "brand_claims", ["status"])
    op.create_table(
        "observation_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crawl_result_id", sa.Integer(), sa.ForeignKey("crawl_results.id"), nullable=False, unique=True),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("company_mentioned", sa.Boolean()),
        sa.Column("company_shortlisted", sa.Boolean()),
        sa.Column("company_recommended", sa.Boolean()),
        sa.Column("claim_accuracy", sa.String(length=50), nullable=False, server_default="unreviewed"),
        sa.Column("citation_valid", sa.Boolean()),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_observation_reviews_crawl_result_id", "observation_reviews", ["crawl_result_id"])
    op.create_index("ix_observation_reviews_reviewer_user_id", "observation_reviews", ["reviewer_user_id"])
    op.create_table(
        "optimization_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("target_question_id", sa.Integer(), sa.ForeignKey("target_questions.id")),
        sa.Column("source_result_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False, server_default="content"),
        sa.Column("priority", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="proposed"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text()),
        sa.Column("target_url", sa.String(length=1000)),
        sa.Column("owner", sa.String(length=255)),
        sa.Column("change_summary", sa.Text()),
        sa.Column("implemented_at", sa.DateTime(timezone=True)),
        sa.Column("verification_result_id", sa.Integer(), sa.ForeignKey("crawl_results.id")),
        sa.Column("verification_summary", sa.Text()),
        sa.Column("concluded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_optimization_actions_project_id", "optimization_actions", ["project_id"])
    op.create_index("ix_optimization_actions_target_question_id", "optimization_actions", ["target_question_id"])
    op.create_index("ix_optimization_actions_priority", "optimization_actions", ["priority"])
    op.create_index("ix_optimization_actions_status", "optimization_actions", ["status"])


def downgrade() -> None:
    op.drop_table("optimization_actions")
    op.drop_table("observation_reviews")
    op.drop_table("brand_claims")
    with op.batch_alter_table("target_questions") as batch:
        batch.drop_index("ix_target_questions_counts_for_visibility")
        batch.drop_index("ix_target_questions_contains_brand")
        batch.drop_index("ix_target_questions_journey_stage")
        batch.drop_column("variants")
        batch.drop_column("counts_for_visibility")
        batch.drop_column("contains_brand")
        batch.drop_column("journey_stage")
