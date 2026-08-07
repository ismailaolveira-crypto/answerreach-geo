#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--" ]]; then
  shift
fi

cd "$(dirname "$0")/../apps/api"
UV_CACHE_DIR=../../.uv-cache uv run python scripts/probe_real_providers.py "$@"
