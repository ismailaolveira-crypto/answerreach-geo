#!/usr/bin/env bash
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! "${ROOT_DIR}/scripts/geo-personal.sh" start; then
  printf '\n启动失败。按回车键关闭窗口。'
  read -r _
  exit 1
fi
