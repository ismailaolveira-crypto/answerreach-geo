# Development Guide

## Runtime Shape

- Backend: FastAPI + SQLAlchemy, default local database `apps/api/geo_platform.db`.
- Frontend: Next.js app in `apps/web`.
- Local API: `http://127.0.0.1:8000`.
- Local Web: `http://127.0.0.1:39003`.

PostgreSQL/Redis compose files remain in `infra/`, but the current MVP acceptance flow uses the local SQLite database.

## Start Locally

From the repository root, start the API:

```bash
pnpm run dev:api
```

Start the web app in another terminal:

```bash
pnpm run dev:web
```

Open:

```text
http://127.0.0.1:39003
```

If the Codex desktop approval reviewer is misconfigured, privileged port-start commands may be blocked. In that case, use the no-port verification suite below until the approval configuration is fixed.

## Verify

Run the whole local gate:

```bash
pnpm run verify
```

Or run individual gates:

```bash
pnpm run check:api
pnpm run check:web
pnpm run build:web
pnpm run verify:local
```

`verify:local` runs the FastAPI TestClient suite without binding local ports. It verifies the current MVP chain:

- project/MVP status
- search crawl and schedule queue
- one-click diagnostic report
- maturity report evidence
- real-provider preflight safety
- report action goals
- article drafting and review context
- content delivery loop
- placement impact goals
- public delivery package
- provider collection summaries

## Real Provider Notes

Provider keys can be stored in Provider `auth_config` or environment variables:

```text
OPENAI_API_KEY=
KIMI_API_KEY=
ARK_API_KEY=
QWEN_API_KEY=
```

Use Provider admin pages to test real channels before using them for collection. Non-Mock providers are blocked by preflight if they are missing key/base URL/model config or have no successful latest test run.

For low-cost smoke validation, prefer:

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/run_real_provider_smoke.py --project-id 9 --provider-ids 9,12 --question-limit 1 --keyword-limit 0 --dry-run
```

Remove `--dry-run` only when network access and API-token consumption are intended.

## Data And Handoff Safety

Do not share this live DB:

```text
apps/api/geo_platform.db
```

It may contain real API keys.

Use the sanitized database and handoff package instead:

```text
outputs/geo_platform.sanitized.db
outputs/geo-platform-handoff-2026-07-06.tar.gz
```

Before refreshing the handoff package, sanitize the copied DB:

```bash
cp apps/api/geo_platform.db outputs/geo_platform.sanitized.db
sqlite3 outputs/geo_platform.sanitized.db "UPDATE llm_providers SET auth_config = json_remove(json_set(COALESCE(auth_config, '{}'), '$.api_key_configured', 1, '$.api_key_redacted', 1), '$.api_key') WHERE json_extract(COALESCE(auth_config, '{}'), '$.api_key') IS NOT NULL; VACUUM; SELECT COUNT(*) FROM llm_providers WHERE json_extract(COALESCE(auth_config, '{}'), '$.api_key') IS NOT NULL;"
```

The final count must be `0`.

## Useful Pages

- `/demo`: demo overview and real-provider evidence.
- `/projects/9`: current demo project.
- `/projects/9/dashboard`: delivery dashboard.
- `/admin/providers`: Provider setup and testing.
- `/admin/queue`: crawl queue operations.
- `/admin/usage`: usage accounting.
- `/reviews`: review queue.
