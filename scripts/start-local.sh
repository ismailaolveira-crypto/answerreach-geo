#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
WEB_MODE="${GEO_WEB_MODE:-development}"

if [[ "$WEB_MODE" != "development" && "$WEB_MODE" != "production" ]]; then
  echo "GEO_WEB_MODE must be development or production." >&2
  exit 2
fi
if [[ "$WEB_MODE" == "production" && ! -f "${ROOT_DIR}/apps/web/.next/BUILD_ID" ]]; then
  echo "Production Web build is missing. Run: pnpm run build:web" >&2
  exit 2
fi

echo "Starting GEO platform locally..."
echo "API: http://127.0.0.1:8000"
echo "Web: http://127.0.0.1:39003"
echo "Web mode: ${WEB_MODE}"
echo "Queue worker: enabled"
echo "Health check after startup: ./scripts/check-local.sh"
echo

if [[ "${GEO_APPLY_MIGRATIONS:-0}" == "1" ]]; then
  echo "Applying explicitly requested database migrations..."
  UV_CACHE_DIR=.uv-cache uv --directory apps/api run alembic upgrade head
  echo
else
  echo "Database migrations: skipped (set GEO_APPLY_MIGRATIONS=1 only after review and backup)"
  echo
fi

echo "Checking database migration revision (read-only)..."
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python -m app.db.migration_guard
echo

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then
    kill "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "${WEB_PID:-}" ]]; then
    kill "$WEB_PID" 2>/dev/null || true
  fi
  if [[ -n "${WORKER_PID:-}" ]]; then
    kill "$WORKER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

pnpm run dev:api &
API_PID=$!

if [[ "$WEB_MODE" == "production" ]]; then
  pnpm run start:web &
else
  pnpm run dev:web &
fi
WEB_PID=$!

pnpm run worker:queue &
WORKER_PID=$!

while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    wait "$API_PID"
    exit $?
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    wait "$WEB_PID"
    exit $?
  fi
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    wait "$WORKER_PID"
    exit $?
  fi
  sleep 1
done
