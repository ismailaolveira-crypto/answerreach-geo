from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = MIGRATIONS_DIR / filename
    spec = spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION_0024 = _load_migration("20260809_0024_workspace_members_local_agents.py")
MIGRATION_0028 = _load_migration("20260810_0028_ensure_workspace_owners.py")


def _apply_upgrade(connection: sa.Connection, migration: ModuleType) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration.upgrade()


def _base_schema(
    connection: sa.Connection, *, include_memberships: bool
) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    companies = sa.Table(
        "companies",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
    )
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
    )
    workspaces = sa.Table(
        "geo_workspaces_v1",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("brand_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    tables = {"companies": companies, "users": users, "workspaces": workspaces}
    if include_memberships:
        tables["memberships"] = _membership_table(metadata)
    metadata.create_all(connection)
    return tables


def _membership_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "geo_workspace_memberships_v1",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("geo_workspaces_v1.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("invited_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("workspace_id", "user_id"),
    )


def _new_engine(tmp_path: Path, name: str) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{tmp_path / name}")


@pytest.mark.parametrize("explicit_status", ["active", "revoked"])
def test_0024_skips_company_wide_backfill_when_any_explicit_membership_exists(
    tmp_path: Path, explicit_status: str
) -> None:
    engine = _new_engine(tmp_path, f"0024-{explicit_status}.db")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        tables = _base_schema(connection, include_memberships=True)
        connection.execute(tables["companies"].insert(), [{"id": 1, "name": "Company"}])
        connection.execute(
            tables["users"].insert(),
            [
                {
                    "id": 10,
                    "company_id": 1,
                    "name": "Company admin",
                    "email": "admin@example.test",
                    "role": "company_admin",
                    "status": "active",
                },
                {
                    "id": 11,
                    "company_id": 1,
                    "name": "Explicit viewer",
                    "email": "viewer@example.test",
                    "role": "viewer",
                    "status": "active",
                },
            ],
        )
        connection.execute(
            tables["workspaces"].insert(),
            [
                {
                    "id": 100,
                    "company_id": 1,
                    "slug": "explicit-boundary",
                    "brand_name": "Explicit",
                    "status": "active",
                },
                {
                    "id": 101,
                    "company_id": 1,
                    "slug": "legacy-empty",
                    "brand_name": "Legacy",
                    "status": "active",
                },
            ],
        )
        connection.execute(
            tables["memberships"].insert(),
            {
                "workspace_id": 100,
                "user_id": 11,
                "role": "viewer",
                "status": explicit_status,
                "joined_at": now,
                "revoked_at": now if explicit_status == "revoked" else None,
            },
        )

        _apply_upgrade(connection, MIGRATION_0024)

        rows = connection.execute(
            sa.select(
                tables["memberships"].c.workspace_id,
                tables["memberships"].c.user_id,
                tables["memberships"].c.role,
                tables["memberships"].c.status,
            ).order_by(
                tables["memberships"].c.workspace_id,
                tables["memberships"].c.user_id,
            )
        ).all()

    engine.dispose()
    assert rows == [
        (100, 11, "viewer", explicit_status),
        (101, 10, "owner", "active"),
        (101, 11, "viewer", "active"),
    ]


def test_0028_never_promotes_or_reactivates_existing_memberships(tmp_path: Path) -> None:
    engine = _new_engine(tmp_path, "0028-role-safety.db")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        tables = _base_schema(connection, include_memberships=True)
        connection.execute(
            tables["companies"].insert(),
            [{"id": company_id, "name": f"Company {company_id}"} for company_id in range(1, 6)],
        )
        connection.execute(
            tables["users"].insert(),
            [
                {
                    "id": 10,
                    "company_id": 1,
                    "name": "Active viewer",
                    "email": "active-viewer@example.test",
                    "role": "viewer",
                    "status": "active",
                },
                {
                    "id": 20,
                    "company_id": 2,
                    "name": "Revoked administrator",
                    "email": "revoked-admin@example.test",
                    "role": "company_admin",
                    "status": "active",
                },
                {
                    "id": 30,
                    "company_id": 3,
                    "name": "Eligible administrator",
                    "email": "eligible-admin@example.test",
                    "role": "company_admin",
                    "status": "active",
                },
                {
                    "id": 40,
                    "company_id": 4,
                    "name": "Existing owner",
                    "email": "existing-owner@example.test",
                    "role": "company_admin",
                    "status": "active",
                },
                {
                    "id": 50,
                    "company_id": None,
                    "name": "Global administrator",
                    "email": "global-admin@example.test",
                    "role": "super_admin",
                    "status": "active",
                },
            ],
        )
        connection.execute(
            tables["workspaces"].insert(),
            [
                {
                    "id": company_id * 100,
                    "company_id": company_id,
                    "slug": f"workspace-{company_id}",
                    "brand_name": f"Workspace {company_id}",
                    "status": "active",
                }
                for company_id in range(1, 6)
            ],
        )
        connection.execute(
            tables["memberships"].insert(),
            [
                {
                    "workspace_id": 100,
                    "user_id": 10,
                    "role": "viewer",
                    "status": "active",
                    "joined_at": now,
                    "revoked_at": None,
                },
                {
                    "workspace_id": 200,
                    "user_id": 20,
                    "role": "viewer",
                    "status": "revoked",
                    "joined_at": now,
                    "revoked_at": now,
                },
                {
                    "workspace_id": 400,
                    "user_id": 40,
                    "role": "owner",
                    "status": "active",
                    "joined_at": now,
                    "revoked_at": None,
                },
            ],
        )

        revoked_at_before = connection.scalar(
            sa.select(tables["memberships"].c.revoked_at).where(
                tables["memberships"].c.workspace_id == 200
            )
        )

        _apply_upgrade(connection, MIGRATION_0028)

        rows = connection.execute(
            sa.select(
                tables["memberships"].c.workspace_id,
                tables["memberships"].c.user_id,
                tables["memberships"].c.role,
                tables["memberships"].c.status,
                tables["memberships"].c.revoked_at,
            ).order_by(
                tables["memberships"].c.workspace_id,
                tables["memberships"].c.user_id,
            )
        ).all()

    engine.dispose()
    assert [(row[:4]) for row in rows] == [
        (100, 10, "viewer", "active"),
        (200, 20, "viewer", "revoked"),
        (300, 30, "owner", "active"),
        (400, 40, "owner", "active"),
    ]
    assert rows[1].revoked_at == revoked_at_before


def test_0024_and_0028_accept_a_fresh_empty_sqlite_database(tmp_path: Path) -> None:
    engine = _new_engine(tmp_path, "fresh-empty.db")
    with engine.begin() as connection:
        _base_schema(connection, include_memberships=False)

        _apply_upgrade(connection, MIGRATION_0024)
        _apply_upgrade(connection, MIGRATION_0028)

        membership_count = connection.scalar(
            sa.text("SELECT count(*) FROM geo_workspace_memberships_v1")
        )

    engine.dispose()
    assert membership_count == 0
