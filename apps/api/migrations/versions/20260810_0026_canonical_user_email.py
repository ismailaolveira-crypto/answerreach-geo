"""enforce canonical case-insensitive user emails

Revision ID: 20260810_0026
Revises: 20260810_0025
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0026"
down_revision: str | None = "20260810_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "uq_users_email_canonical"


def _index_exists() -> bool:
    return INDEX_NAME in {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("users")
    }


def upgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT lower(trim(email)) AS canonical_email, count(*) AS account_count
            FROM users
            GROUP BY lower(trim(email))
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce canonical user emails while case-insensitive duplicates exist"
        )
    op.execute(sa.text("UPDATE users SET email = lower(trim(email))"))
    if not _index_exists():
        op.create_index(
            INDEX_NAME,
            "users",
            [sa.text("lower(email)")],
            unique=True,
        )


def downgrade() -> None:
    if _index_exists():
        op.drop_index(INDEX_NAME, table_name="users")
