#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${ROOT_DIR}/apps/api"
SERVICE_LABEL="com.chunqiu-yuanquan.geo.worker"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
USER_HOME_DIR="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
PLIST_PATH="${USER_HOME_DIR}/Library/LaunchAgents/${SERVICE_LABEL}.plist"

if [[ -f "$PLIST_PATH" && "$(plutil -extract WorkingDirectory raw "$PLIST_PATH" 2>/dev/null || true)" != "$API_DIR" ]]; then
  echo "The installed Worker service belongs to another repository; refusing to remove it." >&2
  exit 3
fi
if launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${USER_ID}" "$PLIST_PATH"
fi
if [[ -f "$PLIST_PATH" ]]; then
  rm "$PLIST_PATH"
fi
echo "Stopped and removed ${SERVICE_LABEL}. Queue data and user logs were preserved."
