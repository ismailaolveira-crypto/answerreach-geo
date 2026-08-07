#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-apps/api/geo_platform.db}"
OUT_DIR="${OUT_DIR:-outputs/real_collection/$(date +%Y%m%d-%H%M%S)}"
PROJECT_ID="${PROJECT_ID:-1}"
PROVIDER_IDS="${PROVIDER_IDS:-}"
QUESTION_IDS="${QUESTION_IDS:-1,2,4}"
READY_ONLY="${READY_ONLY:-1}"

mkdir -p "$OUT_DIR"

if [[ -z "$PROVIDER_IDS" ]]; then
  if [[ "$READY_ONLY" == "1" ]]; then
    PROVIDER_IDS="$(sqlite3 "$DB_PATH" "
      select group_concat(p.id, ',')
      from llm_providers p
      where p.status='active'
        and p.provider_type not in ('mock','browser_observation')
        and (
          select r.ok
          from llm_provider_test_runs r
          where r.provider_id=p.id
          order by r.created_at desc, r.id desc
          limit 1
        ) = 1;
    ")"
  else
    PROVIDER_IDS="$(sqlite3 "$DB_PATH" "select group_concat(id, ',') from llm_providers where status='active' and provider_type not in ('mock','browser_observation');")"
  fi
fi

if [[ -z "$PROVIDER_IDS" ]]; then
  if [[ "$READY_ONLY" == "1" ]]; then
    echo "no tested-ready real providers configured; set READY_ONLY=0 or PROVIDER_IDS=... to run a recovery probe" >&2
  else
    echo "no active real providers configured" >&2
  fi
  exit 1
fi

IFS=',' read -r -a provider_ids <<< "$PROVIDER_IDS"
IFS=',' read -r -a question_ids <<< "$QUESTION_IDS"

header_dir="$(mktemp -d "${TMPDIR:-/tmp}/yuanquan-headers.XXXXXX")"
cleanup_headers() {
  rm -f "$header_dir"/* 2>/dev/null || true
  rmdir "$header_dir" 2>/dev/null || true
}
trap cleanup_headers EXIT

printf '{"project_id":%s,"provider_ids":"%s","question_ids":"%s","prompt_mode":"natural_geo_monitor","items":[]}\n' \
  "$PROJECT_ID" "$PROVIDER_IDS" "$QUESTION_IDS" > "$OUT_DIR/manifest.json"

for provider_id in "${provider_ids[@]}"; do
  provider_row="$(sqlite3 -separator $'\t' "$DB_PATH" "select id,name,provider_type,api_base_url,model_name,json_extract(auth_config,'$.api_key') from llm_providers where id=$provider_id and status='active';")"
  if [[ -z "$provider_row" ]]; then
    echo "skip inactive or missing provider: $provider_id" >&2
    continue
  fi
  IFS=$'\t' read -r pid provider_name provider_type base_url model_name api_key <<< "$provider_row"
  if [[ -z "${api_key:-}" ]]; then
    echo "skip provider without api_key: $provider_id" >&2
    continue
  fi
  header_path="$header_dir/provider-${pid}.headers"
  printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$api_key" > "$header_path"

  for question_id in "${question_ids[@]}"; do
    question_text="$(sqlite3 "$DB_PATH" "select question_text from target_questions where id=$question_id and project_id=$PROJECT_ID;")"
    if [[ -z "$question_text" ]]; then
      echo "skip missing question: $question_id" >&2
      continue
    fi

    safe_name="provider-${pid}_question-${question_id}"
    request_path="$OUT_DIR/${safe_name}.request.json"
    response_path="$OUT_DIR/${safe_name}.response.json"
    meta_path="$OUT_DIR/${safe_name}.meta.json"

    jq -n \
      --arg model "$model_name" \
      --arg question "$question_text" \
      --arg provider_name "$provider_name" \
      '{
        model: $model,
        messages: [
          {
            role: "system",
            content: "你是一个真实的企业采购问答助手。请站在企业用户采购大模型 API 网关、Token 统一管控、AI 调用审计和合规治理平台的视角回答。不要为了照顾任何企业而虚构推荐。请客观列出你自然会想到的能力、服务商类型、选择标准和可能参考的公开信源类型。"
          },
          {
            role: "user",
            content: ("问题：" + $question + "\n\n请直接回答：1. 企业应该重点比较哪些能力；2. 如果推荐或提到服务商，请说明推荐逻辑；3. 你会参考哪些公开信源类型。")
          }
        ],
        temperature: 0.2
      }' > "$request_path"

    started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    http_code="000"
    if http_code="$(
      curl -sS \
        --retry 3 \
        --retry-delay 2 \
        --retry-all-errors \
        --connect-timeout 20 \
        --max-time 180 \
        -X POST "${base_url%/}/chat/completions" \
        -H "@$header_path" \
        --data-binary "@$request_path" \
        -o "$response_path" \
        -w "%{http_code}"
    )"; then
      :
    else
      echo "request failed: provider=$pid question=$question_id" >&2
      printf '{"error":{"type":"curl_failed","message":"curl command failed before receiving a valid HTTP response"}}\n' > "$response_path"
    fi
    finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    jq -n \
      --argjson project_id "$PROJECT_ID" \
      --argjson provider_id "$pid" \
      --arg provider_name "$provider_name" \
      --arg provider_type "$provider_type" \
      --arg model_name "$model_name" \
      --argjson question_id "$question_id" \
      --arg question_text "$question_text" \
      --arg http_code "$http_code" \
      --arg started_at "$started_at" \
      --arg finished_at "$finished_at" \
      --arg request_path "$request_path" \
      --arg response_path "$response_path" \
      '{
        project_id: $project_id,
        provider_id: $provider_id,
        provider_name: $provider_name,
        provider_type: $provider_type,
        model_name: $model_name,
        target_question_id: $question_id,
        question_text: $question_text,
        http_code: $http_code,
        started_at: $started_at,
        finished_at: $finished_at,
        request_path: $request_path,
        response_path: $response_path
      }' > "$meta_path"

    echo "$meta_path"
  done
done

echo "OUT_DIR=$OUT_DIR"
