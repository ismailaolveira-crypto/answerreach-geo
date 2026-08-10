#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${API_URL:-http://127.0.0.1:8000}"
WEB_URL="${WEB_URL:-http://127.0.0.1:39003}"
EXPECTED_WORKER_CWD="${ROOT_DIR}/apps/api"

echo "Checking GEO platform local services..."
echo "API: ${API_URL}"
echo "Web: ${WEB_URL}"
echo

check_url() {
  local label="$1"
  local url="$2"
  if curl -fsS --max-time 5 "$url" >/tmp/geo-platform-check.out 2>/tmp/geo-platform-check.err; then
    echo "OK  ${label}: ${url}"
  else
    echo "ERR ${label}: ${url}"
    echo "    $(tr '\n' ' ' </tmp/geo-platform-check.err | cut -c 1-180)"
    return 1
  fi
}

find_current_repo_worker() {
  local pid
  local worker_cwd
  command -v pgrep >/dev/null 2>&1 || return 1
  command -v lsof >/dev/null 2>&1 || return 1
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    worker_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
    if [[ "$worker_cwd" == "$EXPECTED_WORKER_CWD" ]]; then
      printf '%s\n' "$pid"
      return 0
    fi
  done < <(pgrep -f 'python.*scripts/run_worker\.py' || true)
  return 1
}

failed=0
check_url "API health" "${API_URL}/api/health" || failed=1
check_url "Web app" "${WEB_URL}" || failed=1
if worker_pid="$(find_current_repo_worker)"; then
  echo "OK  Queue worker: PID ${worker_pid} (${EXPECTED_WORKER_CWD})"
  if UV_CACHE_DIR="${ROOT_DIR}/.uv-cache" uv --directory "${ROOT_DIR}/apps/api" run \
    python scripts/check_worker_heartbeat.py --process-id "$worker_pid" --quiet; then
    echo "OK  Queue heartbeat: current global Worker is live"
  else
    echo "ERR Queue heartbeat: PID ${worker_pid} has no live global heartbeat"
    failed=1
  fi
else
  echo "ERR Queue worker: no run_worker.py process belongs to this repository"
  echo "    Expected cwd: ${EXPECTED_WORKER_CWD}"
  failed=1
fi

echo
if [[ "$failed" -eq 0 ]]; then
  echo "Local API, Web, and queue worker look ready."
  echo "Open: ${WEB_URL}"
  echo "Admin providers: ${WEB_URL}/admin/providers"
  echo "Demo project list: ${WEB_URL}/projects"
else
  echo "One or more required local processes are not ready."
  echo "Start the full local stack with: ./scripts/start-local.sh"
  exit 1
fi
