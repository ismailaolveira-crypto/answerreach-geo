"""Add revocable sessions, security throttles and encrypted Provider credentials.

Revision ID: 20260830_0039
Revises: 20260830_0038
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_0039"
down_revision = "20260830_0038"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_columns(table)}


def _migrate_provider_credentials(bind) -> None:
    from app.services.workspace_secrets import normalize_provider_auth_config

    providers = sa.table(
        "llm_providers",
        sa.column("id", sa.Integer()),
        sa.column("auth_config", sa.JSON()),
    )
    rows = bind.execute(sa.select(providers.c.id, providers.c.auth_config)).mappings()
    for row in rows:
        auth_config = dict(row["auth_config"] or {})
        raw_key = auth_config.get("api_key")
        if not isinstance(raw_key, str) or not raw_key.strip() or raw_key == "***configured***":
            continue
        secured = normalize_provider_auth_config(auth_config)
        bind.execute(
            providers.update()
            .where(providers.c.id == row["id"])
            .values(auth_config=secured)
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "credentials_version" not in _column_names(bind, "users"):
        op.add_column(
            "users",
            sa.Column(
                "credentials_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("jti_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
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
        for column in ("user_id", "jti_hash", "expires_at", "revoked_at"):
            op.create_index(f"ix_auth_sessions_{column}", "auth_sessions", [column])

    if "security_rate_limits" not in tables:
        op.create_table(
            "security_rate_limits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("blocked_until", sa.DateTime(timezone=True)),
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
        op.create_index(
            "ix_security_rate_limits_key_hash",
            "security_rate_limits",
            ["key_hash"],
        )
        op.create_index(
            "ix_security_rate_limits_blocked_until",
            "security_rate_limits",
            ["blocked_until"],
        )

    if "llm_providers" in tables:
        _migrate_provider_credentials(bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "security_rate_limits" in tables:
        op.drop_table("security_rate_limits")
    if "auth_sessions" in tables:
        op.drop_table("auth_sessions")
    if "credentials_version" in _column_names(bind, "users"):
        op.drop_column("users", "credentials_version")
