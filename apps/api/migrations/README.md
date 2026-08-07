# Alembic Migrations

Generate a migration after model changes:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```bash
uv run alembic upgrade head
```

Or use the project wrapper:

```bash
uv run python scripts/migrate.py
```

Production deployments must run migrations before starting the API. Keep
`AUTO_CREATE_TABLES=false` in production so schema changes are controlled by
Alembic instead of runtime metadata creation.
