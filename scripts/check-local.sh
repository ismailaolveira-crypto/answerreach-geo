#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
WEB_URL="${WEB_URL:-http://127.0.0.1:3000}"

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

failed=0
check_url "API health" "${API_URL}/api/health" || failed=1
check_url "Web app" "${WEB_URL}" || failed=1

echo
if [[ "$failed" -eq 0 ]]; then
  echo "Local services look ready."
  echo "Open: ${WEB_URL}"
  echo "Admin providers: ${WEB_URL}/admin/providers"
  echo "Demo project list: ${WEB_URL}/projects"
else
  echo "One or more services are not reachable."
  echo "Start both services with: ./scripts/start-local.sh"
  exit 1
fi
