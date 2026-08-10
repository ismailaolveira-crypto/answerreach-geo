#!/usr/bin/env bash
set -euo pipefail

SERVICE_LABEL="com.chunqiu-yuanquan.geo.stack"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
USER_HOME_DIR="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
PLIST_PATH="${USER_HOME_DIR}/Library/LaunchAgents/${SERVICE_LABEL}.plist"

if launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${USER_ID}" "$PLIST_PATH"
fi
if [[ -f "$PLIST_PATH" ]]; then
  rm "$PLIST_PATH"
fi

echo "Stopped and removed ${SERVICE_LABEL}. Existing queue data and logs were preserved."
