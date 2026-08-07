"""initial schema

Revision ID: 20260704_0001
Revises:
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa

revision = "20260704_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Explicit initial schema. Generated from SQLAlchemy metadata and kept auditable.
    # SQLite has no built-in now() scalar; keep PostgreSQL's historical SQL intact
    # while compiling equivalent timestamp defaults for a fresh local database.
    if op.get_bind().dialect.name == "sqlite":
        _text = sa.text
        sa.text = lambda sql: _text("CURRENT_TIMESTAMP" if sql == "now()" else sql)

    op.create_table('companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('industry', sa.String(length=255), nullable=True),
    sa.Column('website_url', sa.String(length=500), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('brand_aliases', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_companies_id'), 'companies', ['id'], unique=False)
    op.create_index(op.f('ix_companies_name'), 'companies', ['name'], unique=False)
    op.create_index(op.f('ix_companies_status'), 'companies', ['status'], unique=False)
    op.create_table('llm_providers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('provider_type', sa.String(length=100), nullable=False),
    sa.Column('api_base_url', sa.String(length=500), nullable=True),
    sa.Column('model_name', sa.String(length=255), nullable=False),
    sa.Column('auth_config', sa.JSON(), nullable=False),
    sa.Column('cost_rule', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_providers_id'), 'llm_providers', ['id'], unique=False)
    op.create_index(op.f('ix_llm_providers_name'), 'llm_providers', ['name'], unique=False)
    op.create_index(op.f('ix_llm_providers_status'), 'llm_providers', ['status'], unique=False)
    op.create_table('queue_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_type', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_queue_jobs_id'), 'queue_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_queue_jobs_job_type'), 'queue_jobs', ['job_type'], unique=False)
    op.create_index(op.f('ix_queue_jobs_priority'), 'queue_jobs', ['priority'], unique=False)
    op.create_index(op.f('ix_queue_jobs_scheduled_at'), 'queue_jobs', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_queue_jobs_status'), 'queue_jobs', ['status'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('target_industry', sa.String(length=255), nullable=True),
    sa.Column('target_audience', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projects_company_id'), 'projects', ['company_id'], unique=False)
    op.create_index(op.f('ix_projects_id'), 'projects', ['id'], unique=False)
    op.create_index(op.f('ix_projects_name'), 'projects', ['name'], unique=False)
    op.create_index(op.f('ix_projects_status'), 'projects', ['status'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('role', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_status'), 'users', ['status'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('actor_role', sa.String(length=100), nullable=True),
    sa.Column('action', sa.String(length=120), nullable=False),
    sa.Column('resource_type', sa.String(length=120), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=True),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('detail_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_role'), 'audit_logs', ['actor_role'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_user_id'), 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_company_id'), 'audit_logs', ['company_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'], unique=False)
    op.create_index(op.f('ix_audit_logs_project_id'), 'audit_logs', ['project_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_id'), 'audit_logs', ['resource_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_type'), 'audit_logs', ['resource_type'], unique=False)
    op.create_table('competitors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('aliases', sa.JSON(), nullable=False),
    sa.Column('website_url', sa.String(length=500), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_competitors_id'), 'competitors', ['id'], unique=False)
    op.create_index(op.f('ix_competitors_name'), 'competitors', ['name'], unique=False)
    op.create_index(op.f('ix_competitors_project_id'), 'competitors', ['project_id'], unique=False)
    op.create_index(op.f('ix_competitors_status'), 'competitors', ['status'], unique=False)
    op.create_table('content_assets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('body_text', sa.Text(), nullable=True),
    sa.Column('publish_channel', sa.String(length=255), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_assets_company_id'), 'content_assets', ['company_id'], unique=False)
    op.create_index(op.f('ix_content_assets_id'), 'content_assets', ['id'], unique=False)
    op.create_index(op.f('ix_content_assets_status'), 'content_assets', ['status'], unique=False)
    op.create_table('crawl_schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('schedule_type', sa.String(length=100), nullable=False),
    sa.Column('interval_hours', sa.Integer(), nullable=False),
    sa.Column('provider_ids', sa.JSON(), nullable=False),
    sa.Column('target_question_ids', sa.JSON(), nullable=False),
    sa.Column('keyword_ids', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crawl_schedules_id'), 'crawl_schedules', ['id'], unique=False)
    op.create_index(op.f('ix_crawl_schedules_next_run_at'), 'crawl_schedules', ['next_run_at'], unique=False)
    op.create_index(op.f('ix_crawl_schedules_project_id'), 'crawl_schedules', ['project_id'], unique=False)
    op.create_index(op.f('ix_crawl_schedules_status'), 'crawl_schedules', ['status'], unique=False)
    op.create_table('crawl_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('task_type', sa.String(length=100), nullable=False),
    sa.Column('schedule_type', sa.String(length=100), nullable=False),
    sa.Column('provider_ids', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crawl_tasks_id'), 'crawl_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_crawl_tasks_project_id'), 'crawl_tasks', ['project_id'], unique=False)
    op.create_index(op.f('ix_crawl_tasks_status'), 'crawl_tasks', ['status'], unique=False)
    op.create_table('keywords',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('keyword', sa.String(length=255), nullable=False),
    sa.Column('keyword_type', sa.String(length=100), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_keywords_id'), 'keywords', ['id'], unique=False)
    op.create_index(op.f('ix_keywords_keyword'), 'keywords', ['keyword'], unique=False)
    op.create_index(op.f('ix_keywords_project_id'), 'keywords', ['project_id'], unique=False)
    op.create_index(op.f('ix_keywords_status'), 'keywords', ['status'], unique=False)
    op.create_table('llm_provider_test_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider_id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('company_name', sa.String(length=255), nullable=True),
    sa.Column('industry', sa.String(length=255), nullable=True),
    sa.Column('answer_summary', sa.Text(), nullable=True),
    sa.Column('raw_answer_preview', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_provider_test_runs_actor_user_id'), 'llm_provider_test_runs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_llm_provider_test_runs_id'), 'llm_provider_test_runs', ['id'], unique=False)
    op.create_index(op.f('ix_llm_provider_test_runs_ok'), 'llm_provider_test_runs', ['ok'], unique=False)
    op.create_index(op.f('ix_llm_provider_test_runs_provider_id'), 'llm_provider_test_runs', ['provider_id'], unique=False)
    op.create_table('maturity_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('report_period', sa.String(length=100), nullable=True),
    sa.Column('total_score', sa.Integer(), nullable=False),
    sa.Column('maturity_level', sa.String(length=50), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('report_json', sa.JSON(), nullable=False),
    sa.Column('pdf_url', sa.String(length=1000), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_maturity_reports_id'), 'maturity_reports', ['id'], unique=False)
    op.create_index(op.f('ix_maturity_reports_project_id'), 'maturity_reports', ['project_id'], unique=False)
    op.create_index(op.f('ix_maturity_reports_status'), 'maturity_reports', ['status'], unique=False)
    op.create_table('target_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('question_type', sa.String(length=100), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_target_questions_id'), 'target_questions', ['id'], unique=False)
    op.create_index(op.f('ix_target_questions_project_id'), 'target_questions', ['project_id'], unique=False)
    op.create_index(op.f('ix_target_questions_status'), 'target_questions', ['status'], unique=False)
    op.create_table('article_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('content_asset_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('target_question_id', sa.Integer(), nullable=True),
    sa.Column('target_keyword_ids', sa.JSON(), nullable=False),
    sa.Column('draft_type', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('generated_by', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['content_asset_id'], ['content_assets.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['target_question_id'], ['target_questions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_article_drafts_id'), 'article_drafts', ['id'], unique=False)
    op.create_index(op.f('ix_article_drafts_project_id'), 'article_drafts', ['project_id'], unique=False)
    op.create_index(op.f('ix_article_drafts_status'), 'article_drafts', ['status'], unique=False)
    op.create_table('content_asset_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('content_asset_id', sa.Integer(), nullable=False),
    sa.Column('total_score', sa.Integer(), nullable=False),
    sa.Column('grade', sa.String(length=10), nullable=False),
    sa.Column('dimension_scores', sa.JSON(), nullable=False),
    sa.Column('issues_json', sa.JSON(), nullable=False),
    sa.Column('suggestions_json', sa.JSON(), nullable=False),
    sa.Column('risk_expressions', sa.JSON(), nullable=False),
    sa.Column('review_type', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['content_asset_id'], ['content_assets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_asset_reviews_id'), 'content_asset_reviews', ['id'], unique=False)
    op.create_index(op.f('ix_content_asset_reviews_status'), 'content_asset_reviews', ['status'], unique=False)
    op.create_table('crawl_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('target_question_id', sa.Integer(), nullable=True),
    sa.Column('keyword_id', sa.Integer(), nullable=True),
    sa.Column('provider_id', sa.Integer(), nullable=True),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('raw_answer', sa.Text(), nullable=False),
    sa.Column('answer_summary', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['keyword_id'], ['keywords.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'], ),
    sa.ForeignKeyConstraint(['target_question_id'], ['target_questions.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['crawl_tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crawl_results_id'), 'crawl_results', ['id'], unique=False)
    op.create_index(op.f('ix_crawl_results_project_id'), 'crawl_results', ['project_id'], unique=False)
    op.create_index(op.f('ix_crawl_results_status'), 'crawl_results', ['status'], unique=False)
    op.create_index(op.f('ix_crawl_results_task_id'), 'crawl_results', ['task_id'], unique=False)
    op.create_table('crawl_task_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=50), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('detail_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['crawl_tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crawl_task_logs_id'), 'crawl_task_logs', ['id'], unique=False)
    op.create_index(op.f('ix_crawl_task_logs_level'), 'crawl_task_logs', ['level'], unique=False)
    op.create_index(op.f('ix_crawl_task_logs_project_id'), 'crawl_task_logs', ['project_id'], unique=False)
    op.create_index(op.f('ix_crawl_task_logs_task_id'), 'crawl_task_logs', ['task_id'], unique=False)
    op.create_table('maturity_score_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('report_id', sa.Integer(), nullable=False),
    sa.Column('dimension', sa.String(length=100), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('max_score', sa.Integer(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.Column('evidence_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['maturity_reports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_maturity_score_items_id'), 'maturity_score_items', ['id'], unique=False)
    op.create_table('system_alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('provider_id', sa.Integer(), nullable=True),
    sa.Column('provider_test_run_id', sa.Integer(), nullable=True),
    sa.Column('alert_type', sa.String(length=120), nullable=False),
    sa.Column('severity', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('detail_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'], ),
    sa.ForeignKeyConstraint(['provider_test_run_id'], ['llm_provider_test_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_system_alerts_alert_type'), 'system_alerts', ['alert_type'], unique=False)
    op.create_index(op.f('ix_system_alerts_company_id'), 'system_alerts', ['company_id'], unique=False)
    op.create_index(op.f('ix_system_alerts_id'), 'system_alerts', ['id'], unique=False)
    op.create_index(op.f('ix_system_alerts_project_id'), 'system_alerts', ['project_id'], unique=False)
    op.create_index(op.f('ix_system_alerts_provider_id'), 'system_alerts', ['provider_id'], unique=False)
    op.create_index(op.f('ix_system_alerts_provider_test_run_id'), 'system_alerts', ['provider_test_run_id'], unique=False)
    op.create_index(op.f('ix_system_alerts_severity'), 'system_alerts', ['severity'], unique=False)
    op.create_index(op.f('ix_system_alerts_status'), 'system_alerts', ['status'], unique=False)
    op.create_table('answer_analysis',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('crawl_result_id', sa.Integer(), nullable=False),
    sa.Column('company_mentioned', sa.Boolean(), nullable=False),
    sa.Column('company_recommended', sa.Boolean(), nullable=False),
    sa.Column('company_rank', sa.Integer(), nullable=True),
    sa.Column('sentiment', sa.String(length=50), nullable=False),
    sa.Column('confidence', sa.Integer(), nullable=False),
    sa.Column('analysis_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['crawl_result_id'], ['crawl_results.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_answer_analysis_id'), 'answer_analysis', ['id'], unique=False)
    op.create_table('article_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('article_draft_id', sa.Integer(), nullable=False),
    sa.Column('total_score', sa.Integer(), nullable=False),
    sa.Column('grade', sa.String(length=10), nullable=False),
    sa.Column('dimension_scores', sa.JSON(), nullable=False),
    sa.Column('issues_json', sa.JSON(), nullable=False),
    sa.Column('suggestions_json', sa.JSON(), nullable=False),
    sa.Column('risk_expressions', sa.JSON(), nullable=False),
    sa.Column('reviewer_id', sa.Integer(), nullable=True),
    sa.Column('review_type', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_draft_id'], ['article_drafts.id'], ),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_article_reviews_id'), 'article_reviews', ['id'], unique=False)
    op.create_index(op.f('ix_article_reviews_status'), 'article_reviews', ['status'], unique=False)
    op.create_table('citation_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('crawl_result_id', sa.Integer(), nullable=False),
    sa.Column('source_title', sa.String(length=500), nullable=True),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('source_domain', sa.String(length=255), nullable=True),
    sa.Column('source_type', sa.String(length=100), nullable=False),
    sa.Column('is_owned', sa.Boolean(), nullable=False),
    sa.Column('is_placed', sa.Boolean(), nullable=False),
    sa.Column('crawlable_score', sa.Integer(), nullable=False),
    sa.Column('ai_readiness_score', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['crawl_result_id'], ['crawl_results.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_citation_sources_id'), 'citation_sources', ['id'], unique=False)
    op.create_index(op.f('ix_citation_sources_source_domain'), 'citation_sources', ['source_domain'], unique=False)
    op.create_table('mentioned_entities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('crawl_result_id', sa.Integer(), nullable=False),
    sa.Column('entity_name', sa.String(length=255), nullable=False),
    sa.Column('entity_type', sa.String(length=100), nullable=False),
    sa.Column('is_company', sa.Boolean(), nullable=False),
    sa.Column('is_competitor', sa.Boolean(), nullable=False),
    sa.Column('mention_count', sa.Integer(), nullable=False),
    sa.Column('recommendation_rank', sa.Integer(), nullable=True),
    sa.Column('context_excerpt', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['crawl_result_id'], ['crawl_results.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mentioned_entities_entity_name'), 'mentioned_entities', ['entity_name'], unique=False)
    op.create_index(op.f('ix_mentioned_entities_id'), 'mentioned_entities', ['id'], unique=False)
    op.create_table('placement_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('content_asset_id', sa.Integer(), nullable=True),
    sa.Column('article_draft_id', sa.Integer(), nullable=True),
    sa.Column('channel', sa.String(length=255), nullable=False),
    sa.Column('target_url', sa.String(length=1000), nullable=True),
    sa.Column('planned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['article_draft_id'], ['article_drafts.id'], ),
    sa.ForeignKeyConstraint(['content_asset_id'], ['content_assets.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_placement_records_channel'), 'placement_records', ['channel'], unique=False)
    op.create_index(op.f('ix_placement_records_id'), 'placement_records', ['id'], unique=False)
    op.create_index(op.f('ix_placement_records_project_id'), 'placement_records', ['project_id'], unique=False)
    op.create_index(op.f('ix_placement_records_status'), 'placement_records', ['status'], unique=False)
    op.create_table('usage_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider_id', sa.Integer(), nullable=True),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('crawl_result_id', sa.Integer(), nullable=True),
    sa.Column('provider_test_run_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=120), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('estimated_cost', sa.Float(), nullable=False),
    sa.Column('currency', sa.String(length=20), nullable=False),
    sa.Column('detail_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['crawl_result_id'], ['crawl_results.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['provider_id'], ['llm_providers.id'], ),
    sa.ForeignKeyConstraint(['provider_test_run_id'], ['llm_provider_test_runs.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['crawl_tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_records_action'), 'usage_records', ['action'], unique=False)
    op.create_index(op.f('ix_usage_records_company_id'), 'usage_records', ['company_id'], unique=False)
    op.create_index(op.f('ix_usage_records_crawl_result_id'), 'usage_records', ['crawl_result_id'], unique=False)
    op.create_index(op.f('ix_usage_records_id'), 'usage_records', ['id'], unique=False)
    op.create_index(op.f('ix_usage_records_project_id'), 'usage_records', ['project_id'], unique=False)
    op.create_index(op.f('ix_usage_records_provider_id'), 'usage_records', ['provider_id'], unique=False)
    op.create_index(op.f('ix_usage_records_provider_test_run_id'), 'usage_records', ['provider_test_run_id'], unique=False)
    op.create_index(op.f('ix_usage_records_task_id'), 'usage_records', ['task_id'], unique=False)



def downgrade() -> None:
    # Drop in dependency-safe reverse order.

    op.drop_index(op.f('ix_usage_records_task_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_provider_test_run_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_provider_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_project_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_crawl_result_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_company_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_action'), table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_index(op.f('ix_placement_records_status'), table_name='placement_records')
    op.drop_index(op.f('ix_placement_records_project_id'), table_name='placement_records')
    op.drop_index(op.f('ix_placement_records_id'), table_name='placement_records')
    op.drop_index(op.f('ix_placement_records_channel'), table_name='placement_records')
    op.drop_table('placement_records')
    op.drop_index(op.f('ix_mentioned_entities_id'), table_name='mentioned_entities')
    op.drop_index(op.f('ix_mentioned_entities_entity_name'), table_name='mentioned_entities')
    op.drop_table('mentioned_entities')
    op.drop_index(op.f('ix_citation_sources_source_domain'), table_name='citation_sources')
    op.drop_index(op.f('ix_citation_sources_id'), table_name='citation_sources')
    op.drop_table('citation_sources')
    op.drop_index(op.f('ix_article_reviews_status'), table_name='article_reviews')
    op.drop_index(op.f('ix_article_reviews_id'), table_name='article_reviews')
    op.drop_table('article_reviews')
    op.drop_index(op.f('ix_answer_analysis_id'), table_name='answer_analysis')
    op.drop_table('answer_analysis')
    op.drop_index(op.f('ix_system_alerts_status'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_severity'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_provider_test_run_id'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_provider_id'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_project_id'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_id'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_company_id'), table_name='system_alerts')
    op.drop_index(op.f('ix_system_alerts_alert_type'), table_name='system_alerts')
    op.drop_table('system_alerts')
    op.drop_index(op.f('ix_maturity_score_items_id'), table_name='maturity_score_items')
    op.drop_table('maturity_score_items')
    op.drop_index(op.f('ix_crawl_task_logs_task_id'), table_name='crawl_task_logs')
    op.drop_index(op.f('ix_crawl_task_logs_project_id'), table_name='crawl_task_logs')
    op.drop_index(op.f('ix_crawl_task_logs_level'), table_name='crawl_task_logs')
    op.drop_index(op.f('ix_crawl_task_logs_id'), table_name='crawl_task_logs')
    op.drop_table('crawl_task_logs')
    op.drop_index(op.f('ix_crawl_results_task_id'), table_name='crawl_results')
    op.drop_index(op.f('ix_crawl_results_status'), table_name='crawl_results')
    op.drop_index(op.f('ix_crawl_results_project_id'), table_name='crawl_results')
    op.drop_index(op.f('ix_crawl_results_id'), table_name='crawl_results')
    op.drop_table('crawl_results')
    op.drop_index(op.f('ix_content_asset_reviews_status'), table_name='content_asset_reviews')
    op.drop_index(op.f('ix_content_asset_reviews_id'), table_name='content_asset_reviews')
    op.drop_table('content_asset_reviews')
    op.drop_index(op.f('ix_article_drafts_status'), table_name='article_drafts')
    op.drop_index(op.f('ix_article_drafts_project_id'), table_name='article_drafts')
    op.drop_index(op.f('ix_article_drafts_id'), table_name='article_drafts')
    op.drop_table('article_drafts')
    op.drop_index(op.f('ix_target_questions_status'), table_name='target_questions')
    op.drop_index(op.f('ix_target_questions_project_id'), table_name='target_questions')
    op.drop_index(op.f('ix_target_questions_id'), table_name='target_questions')
    op.drop_table('target_questions')
    op.drop_index(op.f('ix_maturity_reports_status'), table_name='maturity_reports')
    op.drop_index(op.f('ix_maturity_reports_project_id'), table_name='maturity_reports')
    op.drop_index(op.f('ix_maturity_reports_id'), table_name='maturity_reports')
    op.drop_table('maturity_reports')
    op.drop_index(op.f('ix_llm_provider_test_runs_provider_id'), table_name='llm_provider_test_runs')
    op.drop_index(op.f('ix_llm_provider_test_runs_ok'), table_name='llm_provider_test_runs')
    op.drop_index(op.f('ix_llm_provider_test_runs_id'), table_name='llm_provider_test_runs')
    op.drop_index(op.f('ix_llm_provider_test_runs_actor_user_id'), table_name='llm_provider_test_runs')
    op.drop_table('llm_provider_test_runs')
    op.drop_index(op.f('ix_keywords_status'), table_name='keywords')
    op.drop_index(op.f('ix_keywords_project_id'), table_name='keywords')
    op.drop_index(op.f('ix_keywords_keyword'), table_name='keywords')
    op.drop_index(op.f('ix_keywords_id'), table_name='keywords')
    op.drop_table('keywords')
    op.drop_index(op.f('ix_crawl_tasks_status'), table_name='crawl_tasks')
    op.drop_index(op.f('ix_crawl_tasks_project_id'), table_name='crawl_tasks')
    op.drop_index(op.f('ix_crawl_tasks_id'), table_name='crawl_tasks')
    op.drop_table('crawl_tasks')
    op.drop_index(op.f('ix_crawl_schedules_status'), table_name='crawl_schedules')
    op.drop_index(op.f('ix_crawl_schedules_project_id'), table_name='crawl_schedules')
    op.drop_index(op.f('ix_crawl_schedules_next_run_at'), table_name='crawl_schedules')
    op.drop_index(op.f('ix_crawl_schedules_id'), table_name='crawl_schedules')
    op.drop_table('crawl_schedules')
    op.drop_index(op.f('ix_content_assets_status'), table_name='content_assets')
    op.drop_index(op.f('ix_content_assets_id'), table_name='content_assets')
    op.drop_index(op.f('ix_content_assets_company_id'), table_name='content_assets')
    op.drop_table('content_assets')
    op.drop_index(op.f('ix_competitors_status'), table_name='competitors')
    op.drop_index(op.f('ix_competitors_project_id'), table_name='competitors')
    op.drop_index(op.f('ix_competitors_name'), table_name='competitors')
    op.drop_index(op.f('ix_competitors_id'), table_name='competitors')
    op.drop_table('competitors')
    op.drop_index(op.f('ix_audit_logs_resource_type'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_resource_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_project_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_company_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_role'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_users_status'), table_name='users')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_projects_status'), table_name='projects')
    op.drop_index(op.f('ix_projects_name'), table_name='projects')
    op.drop_index(op.f('ix_projects_id'), table_name='projects')
    op.drop_index(op.f('ix_projects_company_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_queue_jobs_status'), table_name='queue_jobs')
    op.drop_index(op.f('ix_queue_jobs_scheduled_at'), table_name='queue_jobs')
    op.drop_index(op.f('ix_queue_jobs_priority'), table_name='queue_jobs')
    op.drop_index(op.f('ix_queue_jobs_job_type'), table_name='queue_jobs')
    op.drop_index(op.f('ix_queue_jobs_id'), table_name='queue_jobs')
    op.drop_table('queue_jobs')
    op.drop_index(op.f('ix_llm_providers_status'), table_name='llm_providers')
    op.drop_index(op.f('ix_llm_providers_name'), table_name='llm_providers')
    op.drop_index(op.f('ix_llm_providers_id'), table_name='llm_providers')
    op.drop_table('llm_providers')
    op.drop_index(op.f('ix_companies_status'), table_name='companies')
    op.drop_index(op.f('ix_companies_name'), table_name='companies')
    op.drop_index(op.f('ix_companies_id'), table_name='companies')
    op.drop_table('companies')
