#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${ROOT_DIR}/apps/api"
SERVICE_LABEL="com.chunqiu-yuanquan.geo.worker"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
USER_HOME_DIR="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
PLIST_PATH="${USER_HOME_DIR}/Library/LaunchAgents/${SERVICE_LABEL}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This repair command is only for macOS LaunchAgents." >&2
  exit 2
fi
if [[ -f "$PLIST_PATH" && "$(plutil -extract WorkingDirectory raw "$PLIST_PATH" 2>/dev/null || true)" != "$API_DIR" ]]; then
  echo "The installed Worker service belongs to another repository; refusing to repair it." >&2
  exit 3
fi
if launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" >/dev/null 2>&1 && [[ ! -f "$PLIST_PATH" ]]; then
  echo "A loaded Worker service has no verifiable plist; refusing to repair it." >&2
  exit 3
fi
if ! launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" >/dev/null 2>&1; then
  exec /bin/bash "${ROOT_DIR}/scripts/install-macos-worker-service.sh"
fi

launchctl kickstart -k "gui/${USER_ID}/${SERVICE_LABEL}"
for _attempt in {1..20}; do
  if /bin/bash "${ROOT_DIR}/scripts/status-macos-worker-service.sh" >/dev/null 2>&1; then
    echo "Worker service repaired and heartbeat confirmed."
    exit 0
  fi
  sleep 1
done

echo "Worker service restart was requested, but readiness was not confirmed in time." >&2
exit 1
