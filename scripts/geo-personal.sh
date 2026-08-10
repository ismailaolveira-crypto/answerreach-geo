#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_CONFIG_FILE="${ROOT_DIR}/.env.personal"
CONFIG_ROOT="${XDG_CONFIG_HOME:-${HOME}/.config}/chunqiu-yuanquan-geo"
DATA_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}/chunqiu-yuanquan-geo"
CONFIG_FILE="${CONFIG_ROOT}/.env.personal"
BACKUP_ROOT="${DATA_ROOT}/backups"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.personal.yml"
DATA_VOLUME="${GEO_DATA_VOLUME_NAME:-chunqiu_yuanquan_geo_personal_data}"
ARTIFACT_VOLUME="${GEO_ARTIFACT_VOLUME_NAME:-chunqiu_yuanquan_geo_personal_artifacts}"
ACTION="${1:-start}"

compose() {
  docker compose --env-file "$CONFIG_FILE" -f "$COMPOSE_FILE" "$@"
}

fail() {
  printf '\n错误：%s\n' "$1" >&2
  exit 1
}

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "未检测到 Docker Desktop。请先安装并启动 Docker Desktop。"
  docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2。请升级 Docker Desktop。"
  docker info >/dev/null 2>&1 || fail "Docker Desktop 尚未运行。请启动并等待显示 Running 后重试。"
}

port_is_busy() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | tail -n +2 | grep -q .
  else
    curl -fsS --max-time 1 "http://127.0.0.1:${port}/" >/dev/null 2>&1
  fi
}

random_hex() {
  local byte_count="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$byte_count"
  else
    od -An -N"$byte_count" -tx1 /dev/urandom | tr -d ' \n'
  fi
}

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

prepare_config_location() {
  mkdir -p "$CONFIG_ROOT" "$DATA_ROOT"
  chmod 700 "$CONFIG_ROOT" "$DATA_ROOT" 2>/dev/null || true
  if [[ ! -f "$CONFIG_FILE" && -f "$LEGACY_CONFIG_FILE" ]]; then
    cp "$LEGACY_CONFIG_FILE" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true
    printf '已将旧版本机配置迁移到稳定用户目录。\n'
  fi
}

generate_config() {
  [[ ! -e "$CONFIG_FILE" ]] || return 0
  if volume_exists "$DATA_VOLUME" || volume_exists "$ARTIFACT_VOLUME"; then
    fail "检测到已有 GEO 数据卷，但本机密钥不存在。为避免旧 Provider 凭据无法解密，启动已停止。请恢复原 .env.personal。"
  fi
  local port=3000
  local candidate
  for (( candidate=3000; candidate<=3010; candidate++ )); do
    if ! port_is_busy "$candidate"; then
      port="$candidate"
      break
    fi
  done
  port_is_busy "$port" && fail "3000-3010 端口均已被占用，本程序不会结束其他应用。"

  local secret worker_instance_id
  secret="$(random_hex 48)"
  worker_instance_id="$(random_hex 16)"
  [[ ${#secret} -ge 64 ]] || fail "无法生成安全的本机密钥。"

  umask 077
  printf 'GEO_AUTH_SECRET=%s\nGEO_HTTP_PORT=%s\nGEO_WORKER_CONCURRENCY=8\nGEO_WORKER_INSTANCE_ID=%s\n' \
    "$secret" "$port" "$worker_instance_id" >"$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
  printf '已创建本机私密配置（端口 %s，Worker 并发 8）。\n' "$port"
}

ensure_config_keys() {
  if ! grep -q '^GEO_WORKER_CONCURRENCY=' "$CONFIG_FILE"; then
    printf 'GEO_WORKER_CONCURRENCY=8\n' >>"$CONFIG_FILE"
  fi
  if ! grep -q '^GEO_WORKER_INSTANCE_ID=' "$CONFIG_FILE"; then
    printf 'GEO_WORKER_INSTANCE_ID=%s\n' "$(random_hex 16)" >>"$CONFIG_FILE"
  fi
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
}

read_setting() {
  local key="$1"
  sed -n "s/^${key}=//p" "$CONFIG_FILE" | tail -n 1
}

app_url() {
  local port
  port="$(read_setting GEO_HTTP_PORT)"
  [[ "$port" =~ ^[0-9]+$ ]] || fail ".env.personal 中的 GEO_HTTP_PORT 无效。"
  printf 'http://127.0.0.1:%s' "$port"
}

worker_ready() {
  local worker_instance_id
  worker_instance_id="$(read_setting GEO_WORKER_INSTANCE_ID)"
  [[ -n "$worker_instance_id" ]] || return 1
  compose exec -T worker uv run python scripts/check_worker_heartbeat.py \
    --worker-id "personal:${worker_instance_id}" --quiet >/dev/null 2>&1
}

wait_until_ready() {
  local url="$1"
  local deadline=$((SECONDS + 600))
  printf '正在等待 Web、API 和 Worker 就绪'
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 3 "${url}/api/health/ready" >/dev/null 2>&1 \
      && curl -fsS --max-time 3 "${url}/register" >/dev/null 2>&1 \
      && worker_ready; then
      printf ' 完成\n'
      return 0
    fi
    printf '.'
    sleep 3
  done
  printf '\n'
  compose ps || true
  compose logs --tail 80 api web worker gateway || true
  fail "10 分钟内未全部就绪。现有数据卷不会被删除。日志可能包含内部请求路径，请勿整段转发。"
}

open_browser() {
  local url="$1"
  [[ "${GEO_NO_BROWSER:-false}" != "true" ]] || return 0
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
}

show_status() {
  [[ -f "$CONFIG_FILE" ]] || fail "尚未安装。请先运行启动入口。"
  local url
  url="$(app_url)"
  compose ps
  local failed=0
  curl -fsS --max-time 3 "${url}/api/health/ready" >/dev/null 2>&1 \
    && printf 'OK  API 与数据库\n' || { printf 'ERR API 或数据库\n'; failed=1; }
  curl -fsS --max-time 3 "${url}/register" >/dev/null 2>&1 \
    && printf 'OK  Web 界面\n' || { printf 'ERR Web 界面\n'; failed=1; }
  worker_ready \
    && printf 'OK  采集 Worker 心跳\n' || { printf 'ERR 采集 Worker 心跳\n'; failed=1; }
  printf '访问地址：%s\n' "$url"
  return "$failed"
}

restore_running_services() {
  local services="$1"
  [[ -z "$services" ]] || compose start $services >/dev/null 2>&1 || true
}

all_core_services_were_running() {
  local services="$1"
  local required
  for required in api web worker gateway; do
    grep -qx "$required" <<<"$services" || return 1
  done
}

backup_data() {
  local restore_after="${1:-true}"
  [[ -f "$CONFIG_FILE" ]] || fail "尚未安装，无需备份。"
  volume_exists "$DATA_VOLUME" || fail "未找到个人数据卷，备份已停止。"
  volume_exists "$ARTIFACT_VOLUME" || fail "未找到证据卷，备份已停止。"
  local stamp backup_dir running_services
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup_dir="${BACKUP_ROOT}/${stamp}"
  mkdir -p "$backup_dir"
  chmod 700 "$BACKUP_ROOT" "$backup_dir" 2>/dev/null || true
  running_services="$(compose ps --status running --services 2>/dev/null || true)"
  if ! compose stop >/dev/null 2>&1; then
    restore_running_services "$running_services"
    fail "无法暂停全部写入服务，备份已停止。原服务状态已尝试恢复。"
  fi
  cp "$CONFIG_FILE" "${backup_dir}/env.personal"
  chmod 600 "${backup_dir}/env.personal" 2>/dev/null || true
  if ! docker run --rm \
    --mount type=volume,src="$DATA_VOLUME",dst=/source,readonly \
    --mount type=bind,src="$backup_dir",dst=/backup \
    alpine:3.21 sh -c 'test -f /source/geo_platform.db && cd /source && tar -czf /backup/data.tar.gz .'; then
    restore_running_services "$running_services"
    fail "数据库备份失败，原服务状态已尝试恢复。"
  fi
  if ! docker run --rm \
    --mount type=volume,src="$ARTIFACT_VOLUME",dst=/source,readonly \
    --mount type=bind,src="$backup_dir",dst=/backup \
    alpine:3.21 sh -c 'cd /source && tar -czf /backup/artifacts.tar.gz .'; then
    restore_running_services "$running_services"
    fail "证据备份失败，原服务状态已尝试恢复。"
  fi
  if ! docker run --rm --mount type=bind,src="$backup_dir",dst=/backup,readonly \
    alpine:3.21 sh -c 'tar -tzf /backup/data.tar.gz >/dev/null && tar -tzf /backup/artifacts.tar.gz >/dev/null'; then
    restore_running_services "$running_services"
    fail "备份完整性校验失败，不会继续升级。"
  fi
  if command -v shasum >/dev/null 2>&1; then
    (cd "$backup_dir" && shasum -a 256 data.tar.gz artifacts.tar.gz >SHA256SUMS)
  else
    (cd "$backup_dir" && sha256sum data.tar.gz artifacts.tar.gz >SHA256SUMS)
  fi
  printf 'complete\n' >"${backup_dir}/BACKUP_COMPLETE"
  if [[ "$restore_after" == "true" ]]; then
    restore_running_services "$running_services"
    if all_core_services_were_running "$running_services"; then
      wait_until_ready "$(app_url)"
    fi
  fi
  printf '备份已保存到：%s\n' "$backup_dir"
  printf '备份包含本机密钥和可能的 Provider 配置，请勿上传或转发。\n'
}

cd "$ROOT_DIR"
prepare_config_location

case "$ACTION" in
  start)
    require_docker
    first_install=0
    [[ -f "$CONFIG_FILE" ]] || first_install=1
    generate_config
    ensure_config_keys
    url="$(app_url)"
    if volume_exists "$DATA_VOLUME" \
      && docker run --rm --mount type=volume,src="$DATA_VOLUME",dst=/source,readonly \
        alpine:3.21 test -f /source/geo_platform.db; then
      printf '检测到已有数据，启动前先创建一致性备份。\n'
      backup_data false
    fi
    printf '正在构建并启动春秋元泉 GEO。首次启动需要下载镜像，可能需要数分钟。\n'
    compose up -d --build
    wait_until_ready "$url"
    show_status
    if (( first_install == 1 )); then
      open_browser "${url}/register"
    else
      open_browser "$url"
    fi
    ;;
  stop)
    require_docker
    [[ -f "$CONFIG_FILE" ]] || fail "尚未安装。"
    compose stop
    printf '已停止服务。账号、数据库和证据卷已保留。\n'
    ;;
  status)
    require_docker
    show_status
    ;;
  logs)
    require_docker
    [[ -f "$CONFIG_FILE" ]] || fail "尚未安装。"
    printf '以下日志仅供本机排查，不要整段转发。\n'
    compose logs --tail 150 api web worker gateway
    ;;
  backup)
    require_docker
    backup_data
    ;;
  *)
    fail "未知操作：${ACTION}。可用操作：start | stop | status | logs | backup"
    ;;
esac
