#!/usr/bin/env bash
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
rc=0
"${ROOT_DIR}/scripts/geo-personal.sh" status || rc=$?
printf '\n按回车键关闭窗口。'
read -r _
exit "$rc"
