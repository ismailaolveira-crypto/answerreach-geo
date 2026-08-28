#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is only for macOS LaunchAgents." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${ROOT_DIR}/apps/api"
TEMPLATE_PATH="${ROOT_DIR}/infra/launchd/com.chunqiu-yuanquan.geo.worker.plist.template"
SERVICE_LABEL="com.chunqiu-yuanquan.geo.worker"
STACK_SERVICE_LABEL="com.chunqiu-yuanquan.geo.stack"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
USER_HOME_DIR="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
LAUNCH_AGENTS_DIR="${USER_HOME_DIR}/Library/LaunchAgents"
LOG_DIR="${USER_HOME_DIR}/Library/Logs/ChunqiuYuanquanGeo"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${SERVICE_LABEL}.plist"
PYTHON_BIN="${API_DIR}/.venv/bin/python"
CONCURRENCY="${GEO_MANAGED_WORKER_CONCURRENCY:-8}"
RENDER_ONLY_PATH=""

if [[ "${1:-}" == "--render-only" ]]; then
  if [[ -z "${2:-}" || -n "${3:-}" ]]; then
    echo "Usage: $0 [--render-only /absolute/output.plist]" >&2
    exit 2
  fi
  RENDER_ONLY_PATH="$2"
elif [[ "$#" -ne 0 ]]; then
  echo "Usage: $0 [--render-only /absolute/output.plist]" >&2
  exit 2
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "The API virtual environment is missing. Run the repository install command first." >&2
  exit 2
fi
if ! [[ "$CONCURRENCY" =~ ^[0-9]+$ ]] || (( CONCURRENCY < 1 || CONCURRENCY > 125 )); then
  echo "GEO_MANAGED_WORKER_CONCURRENCY must be an integer from 1 to 125." >&2
  exit 2
fi

xml_escape() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

sed_replacement_escape() {
  printf '%s' "$1" | sed -e 's/[&|\\]/\\&/g'
}

render_value() {
  sed_replacement_escape "$(xml_escape "$1")"
}

plist_working_directory() {
  local path="$1"
  plutil -extract WorkingDirectory raw "$path" 2>/dev/null || true
}

if [[ -n "$RENDER_ONLY_PATH" ]]; then
  PLIST_PATH="$RENDER_ONLY_PATH"
else
  mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"
  if launchctl print "gui/${USER_ID}/${STACK_SERVICE_LABEL}" >/dev/null 2>&1; then
    echo "The full GEO stack service is already supervising a Worker; refusing to create a duplicate." >&2
    exit 3
  fi
  if [[ -f "$PLIST_PATH" && "$(plist_working_directory "$PLIST_PATH")" != "$API_DIR" ]]; then
    echo "The installed Worker service belongs to another repository; refusing to replace it." >&2
    exit 3
  fi
fi

WORKER_ID="managed:$(printf '%s' "$ROOT_DIR" | shasum -a 256 | awk '{print substr($1,1,16)}')"
RUNTIME_PATH="$(dirname "$PYTHON_BIN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
TEMP_PLIST="$(mktemp "${PLIST_PATH}.tmp.XXXXXX")"
trap 'rm -f "$TEMP_PLIST"' EXIT

sed \
  -e "s|__PYTHON_BIN__|$(render_value "$PYTHON_BIN")|g" \
  -e "s|__API_DIR__|$(render_value "$API_DIR")|g" \
  -e "s|__CONCURRENCY__|$(render_value "$CONCURRENCY")|g" \
  -e "s|__WORKER_ID__|$(render_value "$WORKER_ID")|g" \
  -e "s|__RUNTIME_PATH__|$(render_value "$RUNTIME_PATH")|g" \
  -e "s|__STDOUT_PATH__|$(render_value "${LOG_DIR}/worker.out.log")|g" \
  -e "s|__STDERR_PATH__|$(render_value "${LOG_DIR}/worker.err.log")|g" \
  "$TEMPLATE_PATH" >"$TEMP_PLIST"

plutil -lint "$TEMP_PLIST" >/dev/null
chmod 600 "$TEMP_PLIST"
mv "$TEMP_PLIST" "$PLIST_PATH"
trap - EXIT

if [[ -n "$RENDER_ONLY_PATH" ]]; then
  echo "Rendered without installing or starting: ${PLIST_PATH}"
  exit 0
fi

if launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${USER_ID}" "$PLIST_PATH"
fi
launchctl bootstrap "gui/${USER_ID}" "$PLIST_PATH"
launchctl enable "gui/${USER_ID}/${SERVICE_LABEL}"
launchctl kickstart -k "gui/${USER_ID}/${SERVICE_LABEL}"

for _attempt in {1..20}; do
  if (
    cd "$API_DIR"
    "$PYTHON_BIN" scripts/check_worker_heartbeat.py --worker-id "$WORKER_ID" --quiet
  ); then
    echo "Installed and started ${SERVICE_LABEL} for ${ROOT_DIR}."
    exit 0
  fi
  sleep 1
done

echo "Worker service was loaded, but its database heartbeat did not become ready in time." >&2
exit 1
