#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/answerreach-browser.XXXXXX")"
API_LOG="$WORK_DIR/api.log"
WEB_LOG="$WORK_DIR/web.log"
API_PID=""
WEB_PID=""
read -r API_PORT WEB_PORT < <(python3 -c '
import socket

sockets = [socket.socket() for _ in range(2)]
for item in sockets:
    item.bind(("127.0.0.1", 0))
print(*(item.getsockname()[1] for item in sockets))
for item in sockets:
    item.close()
')
API_URL="http://127.0.0.1:$API_PORT"
WEB_URL="http://127.0.0.1:$WEB_PORT"

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  [[ -z "$API_PID" ]] || kill "$API_PID" 2>/dev/null || true
  [[ -z "$WEB_PID" ]] || kill "$WEB_PID" 2>/dev/null || true
  [[ -z "$API_PID" ]] || wait "$API_PID" 2>/dev/null || true
  [[ -z "$WEB_PID" ]] || wait "$WEB_PID" 2>/dev/null || true
  if [[ $status -ne 0 ]]; then
    tail -n 120 "$API_LOG" 2>/dev/null || true
    tail -n 120 "$WEB_LOG" 2>/dev/null || true
  fi
  find "$WORK_DIR" -type f -delete
  rmdir "$WORK_DIR"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export DATABASE_URL="sqlite:///$WORK_DIR/geo-ci.db"
export AUTH_SECRET="ci-only-auth-secret-ci-only-auth-secret"
export INTERNAL_PROXY_SECRET="ci-only-proxy-secret-ci-only-proxy-secret"
export PUBLIC_REGISTRATION_ENABLED="true"
export AUTO_CREATE_TABLES="false"
export CORS_ORIGINS="$WEB_URL"
export ALLOWED_HOSTS="127.0.0.1,localhost"
export INTERNAL_API_BASE_URL="$API_URL"
export NEXT_PUBLIC_API_BASE_URL=""
export GEO_E2E_BASE_URL="$WEB_URL"
export GEO_LOCAL_HTTP="true"
export UV_CACHE_DIR="$ROOT_DIR/.uv-cache"
if [[ -z "${GEO_E2E_BROWSER_EXECUTABLE:-}" ]] \
  && [[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  export GEO_E2E_BROWSER_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi

uv --directory "$ROOT_DIR/apps/api" run alembic upgrade head
uv --directory "$ROOT_DIR/apps/api" run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$API_LOG" 2>&1 &
API_PID=$!
pnpm --dir "$ROOT_DIR/apps/web" start --hostname 127.0.0.1 --port "$WEB_PORT" >"$WEB_LOG" 2>&1 &
WEB_PID=$!

for _ in $(seq 1 60); do
  if ! kill -0 "$API_PID" 2>/dev/null || ! kill -0 "$WEB_PID" 2>/dev/null; then
    echo "Isolated API/Web process exited before readiness." >&2
    exit 1
  fi
  if curl --fail --silent "$API_URL/api/health/ready" >/dev/null \
    && curl --fail --silent "$WEB_URL/login" >/dev/null; then
    PYTHONPATH="$ROOT_DIR/apps/api" uv --directory "$ROOT_DIR/apps/api" run python "$ROOT_DIR/scripts/ci_browser_smoke.py"
    exit 0
  fi
  sleep 1
done

echo "Isolated API/Web stack did not become ready within 60 seconds." >&2
exit 1
