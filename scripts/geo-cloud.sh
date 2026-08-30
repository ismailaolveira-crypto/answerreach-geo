#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_CONFIG_FILE="${ROOT_DIR}/.env.cloud"
CONFIG_ROOT="${XDG_CONFIG_HOME:-${HOME}/.config}/chunqiu-yuanquan-geo"
DATA_ROOT="${XDG_DATA_HOME:-${HOME}/.local/share}/chunqiu-yuanquan-geo-cloud"
CONFIG_FILE="${CONFIG_ROOT}/.env.cloud"
BACKUP_ROOT="${DATA_ROOT}/backups"
BACKUP_KEY_FILE="${CONFIG_ROOT}/backup.key"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.cloud.yml"
POSTGRES_VOLUME="${GEO_POSTGRES_VOLUME_NAME:-chunqiu_yuanquan_geo_cloud_postgres}"
ARTIFACT_VOLUME="${GEO_ARTIFACT_VOLUME_NAME:-chunqiu_yuanquan_geo_cloud_artifacts}"
ACTION="${1:-start}"
REQUESTED_DOMAIN="${2:-}"

compose() {
  docker compose --env-file "$CONFIG_FILE" -f "$COMPOSE_FILE" "$@"
}

fail() {
  printf '\n错误：%s\n' "$1" >&2
  exit 1
}

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "未检测到 Docker。请先安装 Docker Engine 与 Compose v2。"
  docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2。"
  docker info >/dev/null 2>&1 || fail "Docker 尚未运行，或当前账号没有访问 Docker 的权限。"
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

ensure_backup_key() {
  if [[ ! -f "$BACKUP_KEY_FILE" ]]; then
    umask 077
    random_hex 32 >"$BACKUP_KEY_FILE"
  fi
  [[ $(wc -c <"$BACKUP_KEY_FILE" | tr -d ' ') -ge 64 ]] \
    || fail "备份密钥无效。请从安全副本恢复 ${BACKUP_KEY_FILE}。"
  chmod 600 "$BACKUP_KEY_FILE" 2>/dev/null || true
}

secure_backup() {
  local mode="$1" input="$2" output="${3:-}"
  local args=(run --rm --no-deps -T
    -v "${BACKUP_KEY_FILE}:/run/secrets/geo-backup-key:ro"
    -v "$(dirname "$input"):/secure-backup"
    api uv run --no-sync python scripts/secure_backup_bundle.py "$mode"
    --key-file /run/secrets/geo-backup-key
    --input "/secure-backup/$(basename "$input")")
  if [[ -n "$output" ]]; then
    args+=(--output "/secure-backup/$(basename "$output")")
  fi
  compose "${args[@]}"
}

prepare_paths() {
  mkdir -p "$CONFIG_ROOT" "$BACKUP_ROOT"
  chmod 700 "$CONFIG_ROOT" "$DATA_ROOT" "$BACKUP_ROOT" 2>/dev/null || true
  if [[ ! -f "$CONFIG_FILE" && -f "$LEGACY_CONFIG_FILE" ]]; then
    cp "$LEGACY_CONFIG_FILE" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true
    printf '已将旧云端配置迁移到稳定的管理员目录。\n'
  fi
}

validate_domain() {
  local domain="$1"
  [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
    && [[ "$domain" == *.* ]] \
    && [[ "$domain" != *..* ]] \
    && [[ "$domain" != http* ]] \
    || fail "域名无效。只填写类似 geo.example.com 的域名，不要带 https://、端口或路径。"
}

read_setting() {
  local key="$1"
  sed -n "s/^${key}=//p" "$CONFIG_FILE" | tail -n 1
}

generate_config() {
  if [[ -f "$CONFIG_FILE" ]]; then
    if [[ -n "$REQUESTED_DOMAIN" ]]; then
      local existing_domain
      existing_domain="$(read_setting GEO_DOMAIN)"
      [[ "$REQUESTED_DOMAIN" == "$existing_domain" ]] \
        || fail "已有配置绑定 ${existing_domain}。为保护现有数据，本程序不会静默改成其他域名。"
    fi
    return 1
  fi
  [[ -n "$REQUESTED_DOMAIN" ]] \
    || fail "首次启动需要域名，例如：./scripts/geo-cloud.sh start geo.example.com"
  validate_domain "$REQUESTED_DOMAIN"
  if volume_exists "$POSTGRES_VOLUME" || volume_exists "$ARTIFACT_VOLUME"; then
    fail "检测到已有云端数据卷，但加密配置不存在。请恢复原 .env.cloud，本程序不会生成新密钥覆盖旧数据。"
  fi

  local auth_secret proxy_secret postgres_password worker_instance_id
  auth_secret="$(random_hex 48)"
  proxy_secret="$(random_hex 48)"
  postgres_password="$(random_hex 36)"
  worker_instance_id="$(random_hex 16)"
  [[ ${#auth_secret} -ge 64 && ${#proxy_secret} -ge 64 ]] || fail "无法生成安全密钥。"

  umask 077
  printf 'GEO_DOMAIN=%s\nGEO_AUTH_SECRET=%s\nGEO_INTERNAL_PROXY_SECRET=%s\nGEO_POSTGRES_PASSWORD=%s\nGEO_WORKER_CONCURRENCY=32\nGEO_WORKER_INSTANCE_ID=%s\n' \
    "$REQUESTED_DOMAIN" "$auth_secret" "$proxy_secret" "$postgres_password" "$worker_instance_id" \
    >"$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
  printf '已创建云端私密配置（权限 0600，密钥未显示）。\n'
  return 0
}

validate_config_contract() {
  local required_key auth_secret proxy_secret
  for required_key in GEO_DOMAIN GEO_AUTH_SECRET GEO_INTERNAL_PROXY_SECRET GEO_POSTGRES_PASSWORD GEO_WORKER_CONCURRENCY GEO_WORKER_INSTANCE_ID; do
    grep -q "^${required_key}=." "$CONFIG_FILE" || fail "云端配置缺少 ${required_key}。请恢复完整配置。"
  done
  validate_domain "$(read_setting GEO_DOMAIN)"
  auth_secret="$(read_setting GEO_AUTH_SECRET)"
  proxy_secret="$(read_setting GEO_INTERNAL_PROXY_SECRET)"
  [[ ${#auth_secret} -ge 64 ]] || fail "GEO_AUTH_SECRET 长度不足。"
  [[ ${#proxy_secret} -ge 64 ]] || fail "GEO_INTERNAL_PROXY_SECRET 长度不足。"
  compose config --quiet
}

worker_ready() {
  local worker_instance_id
  worker_instance_id="$(read_setting GEO_WORKER_INSTANCE_ID)"
  compose exec -T worker uv run --no-sync python scripts/check_worker_heartbeat.py \
    --worker-id "cloud:${worker_instance_id}" --quiet >/dev/null 2>&1
}

internal_ready() {
  compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3)" \
    >/dev/null 2>&1 \
    && compose exec -T gateway wget -q -T 3 -O /dev/null http://127.0.0.1/ \
      >/dev/null 2>&1 \
    && worker_ready
}

wait_until_internal_ready() {
  local deadline=$((SECONDS + 600))
  printf '正在等待数据库、Web、API 和 Worker 就绪'
  while (( SECONDS < deadline )); do
    if internal_ready; then
      printf ' 完成\n'
      return 0
    fi
    printf '.'
    sleep 3
  done
  printf '\n'
  compose ps || true
  compose logs --tail 80 postgres api web worker gateway caddy || true
  fail "10 分钟内未全部就绪。现有数据卷未删除。"
}

public_url() {
  printf 'https://%s' "$(read_setting GEO_DOMAIN)"
}

wait_until_https_ready() {
  local url deadline
  url="$(public_url)"
  deadline=$((SECONDS + 300))
  printf '正在等待域名与 HTTPS 生效'
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 5 "${url}/login" >/dev/null 2>&1 \
      && curl -fsS --max-time 5 "${url}/api/health/ready" >/dev/null 2>&1; then
      printf ' 完成\n'
      return 0
    fi
    printf '.'
    sleep 5
  done
  printf '\n'
  compose logs --tail 80 caddy || true
  fail "内部服务已启动，但公网 HTTPS 尚不可用。请检查域名 A/AAAA 记录以及服务器 80、443 端口。"
}

initialize_admin() {
  [[ -t 0 && -t 1 ]] || fail "首次安装需要交互创建管理员。请在终端运行：./scripts/geo-cloud.sh init-admin"
  local admin_email
  read -r -p "管理员邮箱：" admin_email
  [[ "$admin_email" == *@*.* ]] || fail "管理员邮箱格式无效。"
  compose exec api uv run --no-sync python scripts/init_production.py \
    --admin-email "$admin_email" --prompt-admin-password
  printf '管理员已创建。其他成员请通过工作区邀请加入，不开放公网自助注册。\n'
}

running_services() {
  compose ps --status running --services 2>/dev/null || true
}

restore_services() {
  local services="$1"
  [[ -z "$services" ]] || compose start $services >/dev/null 2>&1 || true
}

all_core_services_were_running() {
  local services="$1" required
  for required in postgres api web worker gateway; do
    grep -qx "$required" <<<"$services" || return 1
  done
}

verify_backup_directory() {
  local requested="$1" file
  [[ -n "$requested" ]] || fail "请提供 .gcm 备份文件。"
  [[ -f "$requested" ]] || fail "备份文件不存在。"
  file="$(cd "$(dirname "$requested")" && pwd -P)/$(basename "$requested")"
  ensure_backup_key
  secure_backup verify "$file"
  printf 'OK  备份已通过 AES-256-GCM 完整性和解密验证。\n'
}

backup_data() {
  local restore_after="${1:-true}"
  [[ -f "$CONFIG_FILE" ]] || fail "尚未安装，无需备份。"
  volume_exists "$POSTGRES_VOLUME" || fail "未找到 PostgreSQL 数据卷。"
  volume_exists "$ARTIFACT_VOLUME" || fail "未找到证据文件卷。"

  local stamp backup_dir services bundle encrypted
  ensure_backup_key
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup_dir="${BACKUP_ROOT}/${stamp}"
  mkdir -p "$backup_dir"
  backup_dir="$(cd "$backup_dir" && pwd -P)"
  chmod 700 "$backup_dir" 2>/dev/null || true
  services="$(running_services)"

  compose stop api worker >/dev/null 2>&1 || {
    restore_services "$services"
    fail "无法暂停 API 与 Worker，备份已停止。"
  }
  cp "$CONFIG_FILE" "${backup_dir}/env.cloud"
  chmod 600 "${backup_dir}/env.cloud" 2>/dev/null || true

  if ! compose exec -T postgres pg_dump -U geo_platform -d geo_platform --format=custom \
    >"${backup_dir}/database.dump"; then
    restore_services "$services"
    fail "PostgreSQL 备份失败，服务状态已尝试恢复。"
  fi
  if ! docker run --rm \
    --mount type=volume,src="$ARTIFACT_VOLUME",dst=/source,readonly \
    --mount type=bind,src="$backup_dir",dst=/backup \
    alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d sh -c 'cd /source && tar -czf /backup/artifacts.tar.gz .'; then
    restore_services "$services"
    fail "证据文件备份失败，服务状态已尝试恢复。"
  fi
  if ! compose exec -T postgres pg_restore --list <"${backup_dir}/database.dump" >/dev/null \
    || ! docker run --rm --mount type=bind,src="$backup_dir",dst=/backup,readonly \
      alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d tar -tzf /backup/artifacts.tar.gz >/dev/null; then
    restore_services "$services"
    fail "备份完整性校验失败。"
  fi
  if command -v shasum >/dev/null 2>&1; then
    (cd "$backup_dir" && shasum -a 256 database.dump artifacts.tar.gz env.cloud >SHA256SUMS)
  else
    (cd "$backup_dir" && sha256sum database.dump artifacts.tar.gz env.cloud >SHA256SUMS)
  fi
  printf 'complete\n' >"${backup_dir}/BACKUP_COMPLETE"
  bundle="${backup_dir}/geo-backup.tar.gz"
  encrypted="${backup_dir}/geo-backup-${stamp}.gcm"
  tar -czf "$bundle" -C "$backup_dir" database.dump artifacts.tar.gz env.cloud SHA256SUMS BACKUP_COMPLETE
  secure_backup encrypt "$bundle" "$encrypted"
  secure_backup verify "$encrypted"
  rm -f "${backup_dir}/database.dump" "${backup_dir}/artifacts.tar.gz" \
    "${backup_dir}/env.cloud" "${backup_dir}/SHA256SUMS" \
    "${backup_dir}/BACKUP_COMPLETE" "$bundle"

  if [[ "$restore_after" == "true" ]]; then
    restore_services "$services"
    if all_core_services_were_running "$services"; then
      wait_until_internal_ready
    fi
  fi
  printf '加密备份已保存到：%s\n' "$encrypted"
  printf '请另行安全保存备份密钥 %s；丢失后无法恢复。\n' "$BACKUP_KEY_FILE"
}

show_status() {
  [[ -f "$CONFIG_FILE" ]] || fail "尚未安装。"
  compose ps
  local failed=0 url
  url="$(public_url)"
  internal_ready \
    && printf 'OK  数据库、API、Web 与 Worker\n' \
    || { printf 'ERR 内部服务未全部就绪\n'; failed=1; }
  curl -fsS --max-time 5 "${url}/api/health/ready" >/dev/null 2>&1 \
    && printf 'OK  公网 HTTPS\n' \
    || { printf 'ERR 公网 HTTPS\n'; failed=1; }
  printf '访问地址：%s\n' "$url"
  return "$failed"
}

cd "$ROOT_DIR"
prepare_paths

case "$ACTION" in
  start)
    require_docker
    new_database=0
    volume_exists "$POSTGRES_VOLUME" || new_database=1
    generate_config || true
    validate_config_contract
    if (( new_database == 0 )) && volume_exists "$ARTIFACT_VOLUME"; then
      printf '检测到已有云端数据，升级前先创建可校验备份。\n'
      compose build api
      compose up -d postgres
      backup_data false
    fi
    printf '正在构建并启动春秋元泉 GEO 云端服务。\n'
    compose up -d --build
    wait_until_internal_ready
    if (( new_database == 1 )); then
      initialize_admin
    fi
    wait_until_https_ready
    show_status
    ;;
  init-admin)
    require_docker
    [[ -f "$CONFIG_FILE" ]] || fail "尚未安装。"
    validate_config_contract
    initialize_admin
    ;;
  stop)
    require_docker
    [[ -f "$CONFIG_FILE" ]] || fail "尚未安装。"
    compose stop
    printf '服务已停止，数据库、证据和 HTTPS 证书卷均保留。\n'
    ;;
  status)
    require_docker
    validate_config_contract
    show_status
    ;;
  logs)
    require_docker
    validate_config_contract
    printf '以下日志仅供管理员排查，不要整段转发。\n'
    compose logs --tail 150 postgres api web worker gateway caddy
    ;;
  backup)
    require_docker
    validate_config_contract
    backup_data true
    ;;
  verify-backup)
    require_docker
    verify_backup_directory "$REQUESTED_DOMAIN"
    ;;
  *)
    fail "未知操作：${ACTION}。可用操作：start | init-admin | stop | status | logs | backup | verify-backup"
    ;;
esac
