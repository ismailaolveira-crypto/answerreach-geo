#!/usr/bin/env bash
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
"${ROOT_DIR}/scripts/geo-personal.sh" stop
exit $?
