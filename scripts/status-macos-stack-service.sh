#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_API_CWD="${ROOT_DIR}/apps/api"
EXPECTED_WEB_CWD="${ROOT_DIR}/apps/web"
SERVICE_LABEL="com.chunqiu-yuanquan.geo.stack"
USER_ID="$(id -u)"

SERVICE_STATE="$(launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" 2>/dev/null || true)"
if [[ -z "$SERVICE_STATE" ]]; then
  echo "OFFLINE: ${SERVICE_LABEL} is not loaded for this user."
  exit 1
fi
SERVICE_PID="$(printf '%s\n' "$SERVICE_STATE" | awk '$1 == "pid" && $2 == "=" {print $3; exit}')"
if [[ -z "$SERVICE_PID" ]]; then
  echo "RECOVERING: ${SERVICE_LABEL} is loaded but has no active supervisor PID yet."
  exit 1
fi

is_descendant_of_service() {
  local child_pid="$1"
  local current_pid="$child_pid"
  local parent_pid
  while [[ "$current_pid" -gt 1 ]]; do
    [[ "$current_pid" == "$SERVICE_PID" ]] && return 0
    parent_pid="$(ps -o ppid= -p "$current_pid" 2>/dev/null | tr -d ' ')"
    [[ -n "$parent_pid" ]] || return 1
    current_pid="$parent_pid"
  done
  return 1
}

check_listener_cwd() {
  local port="$1"
  local expected_cwd="$2"
  local pid
  local actual_cwd
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN | head -n 1)"
  [[ -n "$pid" ]] || return 1
  is_descendant_of_service "$pid" || return 1
  actual_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  [[ "$actual_cwd" == "$expected_cwd" ]]
}

if ! check_listener_cwd 39003 "$EXPECTED_WEB_CWD"; then
  echo "RECOVERING: Web listener is missing or belongs to another checkout."
  exit 1
fi
if ! check_listener_cwd 8000 "$EXPECTED_API_CWD"; then
  echo "RECOVERING: API listener is missing or belongs to another checkout."
  exit 1
fi
curl -fsS --max-time 5 http://127.0.0.1:39003 >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null

matched=0
while IFS= read -r worker_pid; do
  [[ -n "$worker_pid" ]] || continue
  is_descendant_of_service "$worker_pid" || continue
  worker_cwd="$(lsof -a -p "$worker_pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  [[ "$worker_cwd" == "$EXPECTED_API_CWD" ]] || continue
  if UV_CACHE_DIR="${ROOT_DIR}/.uv-cache" uv --directory "${ROOT_DIR}/apps/api" run \
    python scripts/check_worker_heartbeat.py --process-id "$worker_pid"; then
    echo "ONLINE: Web, API, and current-repository Worker PID ${worker_pid} are ready."
    matched=1
    break
  fi
done < <(pgrep -f 'python.*scripts/run_worker\.py' || true)

if [[ "$matched" -ne 1 ]]; then
  echo "RECOVERING: service is loaded, but no current-repository Worker has a live heartbeat yet."
  exit 1
fi
