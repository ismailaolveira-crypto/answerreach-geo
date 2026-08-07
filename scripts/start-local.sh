#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Starting GEO platform locally..."
echo "API: http://127.0.0.1:8000"
echo "Web: http://127.0.0.1:3000"
echo "Queue worker: enabled"
echo "Health check after startup: ./scripts/check-local.sh"
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

pnpm run dev:web &
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
