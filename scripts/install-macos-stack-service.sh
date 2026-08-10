#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is only for macOS LaunchAgents." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="${ROOT_DIR}/infra/launchd/com.chunqiu-yuanquan.geo.stack.plist.template"
START_SCRIPT="${ROOT_DIR}/scripts/start-local.sh"
SERVICE_LABEL="com.chunqiu-yuanquan.geo.stack"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"
USER_HOME_DIR="$(dscl . -read "/Users/${USER_NAME}" NFSHomeDirectory | awk '{print $2}')"
LAUNCH_AGENTS_DIR="${USER_HOME_DIR}/Library/LaunchAgents"
LOG_DIR="${USER_HOME_DIR}/Library/Logs/ChunqiuYuanquanGeo"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${SERVICE_LABEL}.plist"
UV_BIN="$(command -v uv || true)"
PNPM_BIN="$(command -v pnpm || true)"
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

if [[ -z "$UV_BIN" || -z "$PNPM_BIN" ]]; then
  echo "uv and pnpm must both be available in the current login environment." >&2
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

if [[ -n "$RENDER_ONLY_PATH" ]]; then
  PLIST_PATH="$RENDER_ONLY_PATH"
else
  mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"
fi
TEMP_PLIST="$(mktemp "${PLIST_PATH}.tmp.XXXXXX")"
trap 'rm -f "$TEMP_PLIST"' EXIT

RUNTIME_PATH="$(dirname "$UV_BIN"):$(dirname "$PNPM_BIN"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
sed \
  -e "s|__START_SCRIPT__|$(render_value "$START_SCRIPT")|g" \
  -e "s|__ROOT_DIR__|$(render_value "$ROOT_DIR")|g" \
  -e "s|__RUNTIME_PATH__|$(render_value "$RUNTIME_PATH")|g" \
  -e "s|__UV_CACHE_DIR__|$(render_value "${ROOT_DIR}/.uv-cache")|g" \
  -e "s|__STDOUT_PATH__|$(render_value "${LOG_DIR}/stack.out.log")|g" \
  -e "s|__STDERR_PATH__|$(render_value "${LOG_DIR}/stack.err.log")|g" \
  "$TEMPLATE_PATH" >"$TEMP_PLIST"

plutil -lint "$TEMP_PLIST" >/dev/null
chmod 600 "$TEMP_PLIST"
mv "$TEMP_PLIST" "$PLIST_PATH"
trap - EXIT

if [[ -n "$RENDER_ONLY_PATH" ]]; then
  echo "Rendered without installing or starting: ${PLIST_PATH}"
  exit 0
fi

echo "Building optimized Web runtime before service handoff..."
pnpm run build:web

echo "Selection-only dispatch is enabled: historical observation jobs remain read-only."
echo "Only a fresh current-page submission can create executable observation work."
echo "Installing current-repository Web/API/Worker service: ${ROOT_DIR}"
if launchctl print "gui/${USER_ID}/${SERVICE_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${USER_ID}" "$PLIST_PATH"
fi

stop_current_repo_listener() {
  local port="$1"
  local expected_cwd="$2"
  local pid
  local actual_cwd
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN | head -n 1)"
  [[ -n "$pid" ]] || return 0
  actual_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  if [[ "$actual_cwd" != "$expected_cwd" ]]; then
    echo "Port ${port} belongs to another process checkout: ${actual_cwd}" >&2
    return 1
  fi
  echo "Handing current-repository port ${port} from manual PID ${pid} to launchd."
  kill "$pid"
}

if ! stop_current_repo_listener 39003 "${ROOT_DIR}/apps/web" || \
   ! stop_current_repo_listener 8000 "${ROOT_DIR}/apps/api"; then
  rm "$PLIST_PATH"
  exit 1
fi
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if ! lsof -nP -iTCP:39003 -sTCP:LISTEN >/dev/null 2>&1 && \
     ! lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if lsof -nP -iTCP:39003 -sTCP:LISTEN >/dev/null 2>&1 || \
   lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Ports 39003 or 8000 did not become available; service was not loaded." >&2
  rm "$PLIST_PATH"
  exit 1
fi
launchctl bootstrap "gui/${USER_ID}" "$PLIST_PATH"
launchctl enable "gui/${USER_ID}/${SERVICE_LABEL}"
launchctl kickstart -k "gui/${USER_ID}/${SERVICE_LABEL}"

echo "Installed and started ${SERVICE_LABEL}."
echo "Check: pnpm run service:status"
echo "Logs: ${LOG_DIR}"
