#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${ROOT_DIR}/apps/api"
SERVICE_LABEL="com.chunqiu-yuanquan.geo.worker"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
USER_HOME_DIR="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
PLIST_PATH="${USER_HOME_DIR}/Library/LaunchAgents/${SERVICE_LABEL}.plist"
PYTHON_BIN="${API_DIR}/.venv/bin/python"
WORKER_ID="managed:$(printf '%s' "$ROOT_DIR" | shasum -a 256 | awk '{print substr($1,1,16)}')"

if [[ ! -f "$PLIST_PATH" ]]; then
  echo "OFFLINE: ${SERVICE_LABEL} is not installed for this user."
  exit 1
fi
if [[ "$(plutil -extract WorkingDirectory raw "$PLIST_PATH" 2>/dev/null || true)" != "$API_DIR" ]]; then
  echo "CONFLICT: ${SERVICE_LABEL} belongs to another repository."
  exit 2
fi
SERVICE_STATE="$(launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" 2>/dev/null || true)"
SERVICE_PID="$(printf '%s\n' "$SERVICE_STATE" | awk '$1 == "pid" && $2 == "=" {print $3; exit}')"
if [[ -z "$SERVICE_PID" ]]; then
  echo "RECOVERING: service is loaded but has no Worker PID yet."
  exit 1
fi
WORKER_CWD="$(lsof -a -p "$SERVICE_PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
if [[ "$WORKER_CWD" != "$API_DIR" ]]; then
  echo "CONFLICT: Worker PID ${SERVICE_PID} belongs to ${WORKER_CWD:-unknown}."
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "RECOVERING: the API virtual environment is not available for the heartbeat check."
  exit 1
fi
(
  cd "$API_DIR"
  "$PYTHON_BIN" scripts/check_worker_heartbeat.py \
    --process-id "$SERVICE_PID" --worker-id "$WORKER_ID" --quiet
)
echo "ONLINE: managed Worker PID ${SERVICE_PID} is running from the current repository."
