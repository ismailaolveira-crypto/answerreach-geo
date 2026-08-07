"""Independently recompute competitor metrics from the read-only SQLite archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean
import unicodedata


BRANDS = {
    "chunqiu-yuanquan": (
        "春秋元泉", "智能永信", "ichunqiu", "icqtoken",
    ),
    "raytoken": (
        "RayToken", "RayToken AI安全网关", "盛邦安全 AI安全网关", "WebRAY AI安全网关",
    ),
    "qax-ai-gateway": (
        "奇安信AI安全网关", "QAX AI安全网关", "奇安信 AI Gateway", "vKey",
    ),
    "aigate": (
        "AIGate", "Enterprise AI Gateway", "企业 AI Token 统一管理", "万根 AI 网关",
    ),
    "aliyun-ai-gateway": (
        "阿里云AI网关", "Aliyun AI Gateway", "API Gateway AI网关",
    ),
    "tencent-ai-agent-security-gateway": (
        "腾讯云AI Agent安全网关", "AI Agent安全网关", "腾讯云 LLM Security Gateway",
    ),
}
BASELINE_KEY = "chunqiu-yuanquan"
NEGATIVE_MARKERS = (
    "不推荐", "不建议", "不是首选", "非首选", "未推荐", "没有推荐",
    "不列入候选", "未列入候选", "未进入候选", "没有提及", "未提及", "不引用",
)
RECOMMENDATION_MARKERS = ("推荐", "首选", "优先", "建议选择", "值得考虑")
CANDIDATE_MARKERS = (
    "候选", "入选", "备选", "推荐", "首选", "优先",
    "典型代表", "代表产品", "代表平台", "代表",
)


def independent_pattern(alias: str) -> re.Pattern[str]:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", alias))
    body = r"\s*".join(re.escape(character) for character in compact)
    left = r"(?<![A-Za-z0-9_])" if compact[0].isascii() and compact[0].isalnum() else ""
    right = r"(?![A-Za-z0-9_])" if compact[-1].isascii() and compact[-1].isalnum() else ""
    return re.compile(f"{left}{body}{right}", re.IGNORECASE)


PATTERNS = {
    key: [independent_pattern(alias) for alias in aliases]
    for key, aliases in BRANDS.items()
}


def brand_matches(answer: str, key: str) -> list[re.Match[str]]:
    found = [match for pattern in PATTERNS[key] for match in pattern.finditer(answer)]
    found.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
    deduplicated: list[re.Match[str]] = []
    for match in found:
        if deduplicated and match.start() < deduplicated[-1].end():
            continue
        deduplicated.append(match)
    return deduplicated


def table_position(answer: str, match: re.Match[str]) -> int | None:
    lines = answer.splitlines(keepends=True)
    offset = 0
    matched_line_index = -1
    for index, line in enumerate(lines):
        if offset <= match.start() < offset + len(line):
            matched_line_index = index
            break
        offset += len(line)
    if matched_line_index < 0:
        return None
    line = lines[matched_line_index].strip()
    if "|" in line:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        numeric = re.match(r"^(\d{1,2})$", cells[0]) if cells else None
        if numeric:
            return int(numeric.group(1))
        separator = next(
            (
                index
                for index in range(matched_line_index - 1, -1, -1)
                if re.match(r"^\s*\|?\s*:?-{3,}", lines[index])
            ),
            None,
        )
        if separator is not None:
            rows = [
                row
                for row in lines[separator + 1:matched_line_index + 1]
                if "|" in row and row.strip(" |\r\n")
            ]
            return len(rows) or None
    if "\t" in line:
        cells = [cell.strip() for cell in line.split("\t")]
        numeric = re.match(r"^(\d{1,2})$", cells[0]) if cells else None
        if numeric:
            return int(numeric.group(1))
        header = next(
            (
                index
                for index in range(matched_line_index - 1, -1, -1)
                if "\t" in lines[index]
                and any(
                    marker in lines[index]
                    for marker in ("平台", "产品", "厂商", "品牌", "方案", "排名", "代表")
                )
            ),
            None,
        )
        if header is not None:
            rows = [
                row
                for row in lines[header + 1:matched_line_index + 1]
                if "\t" in row and row.strip()
            ]
            return len(rows) or None
    return None


def explicit_rank(answer: str, match: re.Match[str]) -> int | None:
    line_start = answer.rfind("\n", 0, match.start()) + 1
    line_end = answer.find("\n", match.end())
    line = answer[line_start:line_end if line_end >= 0 else len(answer)].strip()
    numbered = re.match(r"^(?:#{1,6}\s*)?(\d{1,2})[.、)]\s*", line)
    return int(numbered.group(1)) if numbered else table_position(answer, match)


def marker_distance(
    context: str,
    relative_start: int,
    relative_end: int,
    markers: tuple[str, ...],
) -> int | None:
    distances: list[int] = []
    for marker in markers:
        for found in re.finditer(re.escape(marker.casefold()), context):
            if found.end() <= relative_start:
                distances.append(relative_start - found.end())
            elif found.start() >= relative_end:
                distances.append(found.start() - relative_end)
            else:
                distances.append(0)
    return min(distances) if distances else None


def classify(answer: str, match: re.Match[str]) -> tuple[str, int | None]:
    context_start = max(0, match.start() - 55)
    context_end = min(len(answer), match.end() + 55)
    context = answer[context_start:context_end].casefold()
    relative_start = match.start() - context_start
    relative_end = match.end() - context_start
    negative = marker_distance(context, relative_start, relative_end, NEGATIVE_MARKERS)
    recommended = marker_distance(context, relative_start, relative_end, RECOMMENDATION_MARKERS)
    candidate = marker_distance(context, relative_start, relative_end, CANDIDATE_MARKERS)
    rank = explicit_rank(answer, match)
    if negative is not None and negative <= 24 and (
        recommended is None or negative <= recommended
    ):
        return "negative", rank
    if recommended is not None and recommended <= 24:
        return "recommended", rank
    if rank is not None or (candidate is not None and candidate <= 24):
        return "shortlisted", rank
    return "mentioned", rank


def answer_hits(answer: str) -> dict[str, dict]:
    normalized = unicodedata.normalize("NFKC", answer or "")
    hits: dict[str, dict] = {}
    priority = {"negative": 0, "recommended": 1, "shortlisted": 2, "mentioned": 3}
    for key in BRANDS:
        matches = brand_matches(normalized, key)
        if not matches:
            continue
        classified = [(*classify(normalized, match), match) for match in matches]
        status, _, _ = min(classified, key=lambda item: (priority[item[0]], item[2].start()))
        explicit_rank = min(
            (item[1] for item in classified if item[1] is not None),
            default=None,
        )
        hits[key] = {
            "status": status,
            "explicit_rank": explicit_rank,
            "first_start": matches[0].start(),
        }
    return hits


def parse_database_time(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def load_rows(args: argparse.Namespace, api_payload: dict | None) -> list[tuple]:
    query = (
        "SELECT id, model_key, question_plan_id, answer_text "
        "FROM geo_evidence_v1 WHERE workspace_id = ? AND is_real_provider_evidence = 1"
    )
    params: list[object] = [args.workspace_id]
    scope = api_payload.get("scope", {}) if api_payload else {}
    model = scope.get("model_key") or args.model
    question_id = scope.get("question_plan_id") or args.question_id
    date_from = parse_database_time(scope.get("date_from"))
    date_to = parse_database_time(scope.get("date_to"))
    if api_payload is None and args.period_days:
        date_to_value = datetime.now(timezone.utc)
        date_from_value = date_to_value - timedelta(days=args.period_days)
        date_from = date_from_value.replace(tzinfo=None).isoformat(sep=" ")
        date_to = date_to_value.replace(tzinfo=None).isoformat(sep=" ")
    if date_from:
        query += " AND captured_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND captured_at <= ?"
        params.append(date_to)
    if model:
        query += " AND model_key = ?"
        params.append(model)
    if question_id:
        query += " AND question_plan_id = ?"
        params.append(question_id)
    query += " ORDER BY id"
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    rows = connection.execute(query, params).fetchall()
    connection.close()
    return rows


def recompute(rows: list[tuple]) -> dict:
    analyses = [
        {
            "evidence_id": evidence_id,
            "model_key": model_key,
            "question_plan_id": question_id,
            "hits": answer_hits(answer),
        }
        for evidence_id, model_key, question_id, answer in rows
    ]
    brands: dict[str, dict] = {}
    answer_has_comparison: set[int] = set()
    answer_has_competitor_win: set[int] = set()
    for key in BRANDS:
        matched = [analysis for analysis in analyses if key in analysis["hits"]]
        ranks = [
            analysis["hits"][key]["explicit_rank"]
            for analysis in matched
            if analysis["hits"][key]["explicit_rank"] is not None
        ]
        wins = 0
        comparable = 0
        win_evidence_ids: list[int] = []
        if key != BASELINE_KEY:
            for analysis in analyses:
                baseline = analysis["hits"].get(BASELINE_KEY)
                competitor = analysis["hits"].get(key)
                is_comparable = False
                is_win = False
                if baseline and competitor:
                    baseline_rank = baseline["explicit_rank"]
                    competitor_rank = competitor["explicit_rank"]
                    is_comparable = baseline_rank is not None and competitor_rank is not None
                    is_win = is_comparable and competitor_rank < baseline_rank
                elif competitor and not baseline:
                    is_comparable = competitor["status"] in {"shortlisted", "recommended"}
                    is_win = is_comparable
                elif baseline and not competitor:
                    is_comparable = baseline["status"] in {"shortlisted", "recommended"}
                if is_comparable:
                    comparable += 1
                    answer_has_comparison.add(analysis["evidence_id"])
                if is_win:
                    wins += 1
                    win_evidence_ids.append(analysis["evidence_id"])
                    answer_has_competitor_win.add(analysis["evidence_id"])
        top3_count = sum(rank <= 3 for rank in ranks)
        brands[key] = {
            "hit_answer_count": len(matched),
            "wins_over_baseline": wins,
            "comparable_answers": comparable,
            "top3_count": top3_count,
            "top3_rate": round(top3_count / len(ranks) * 100, 1) if ranks else 0.0,
            "explicit_average_position": round(mean(ranks), 2) if ranks else None,
            "win_evidence_ids": win_evidence_ids,
        }
    return {
        "answer_count": len(analyses),
        "comparable_answer_count": len(answer_has_comparison),
        "answers_where_competitor_wins": len(answer_has_competitor_win),
        "brands": brands,
    }


def compare_with_api(result: dict, api_payload: dict) -> list[str]:
    differences: list[str] = []
    summary = api_payload["summary"]
    for field in (
        "answer_count", "comparable_answer_count", "answers_where_competitor_wins",
    ):
        if result[field] != summary[field]:
            differences.append(f"summary.{field}: independent={result[field]} api={summary[field]}")
    api_brands = {item["key"]: item for item in api_payload["brands"]}
    fields = (
        "hit_answer_count", "wins_over_baseline", "comparable_answers", "top3_count",
        "top3_rate", "explicit_average_position",
    )
    for key, brand in result["brands"].items():
        for field in fields:
            if brand[field] != api_brands[key][field]:
                differences.append(
                    f"brands.{key}.{field}: independent={brand[field]} "
                    f"api={api_brands[key][field]}"
                )
        api_evidence_ids = sorted(item["evidence_id"] for item in api_brands[key]["win_evidence"])
        if sorted(brand["win_evidence_ids"]) != api_evidence_ids:
            differences.append(
                f"brands.{key}.win_evidence_ids: "
                f"independent={sorted(brand['win_evidence_ids'])} api={api_evidence_ids}"
            )
    return differences


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("geo_platform.db"))
    parser.add_argument("--workspace-id", type=int, default=1)
    parser.add_argument("--period-days", type=int)
    parser.add_argument("--model")
    parser.add_argument("--question-id", type=int)
    parser.add_argument("--compare-json", type=Path)
    args = parser.parse_args()
    api_payload = json.loads(args.compare_json.read_text()) if args.compare_json else None
    result = recompute(load_rows(args, api_payload))
    differences = compare_with_api(result, api_payload) if api_payload else []
    result["comparison"] = {
        "api_payload": str(args.compare_json) if args.compare_json else None,
        "exact_match": not differences if api_payload else None,
        "differences": differences,
    }
    result["verified_win_evidence_count"] = sum(
        len(item["win_evidence_ids"]) for item in result["brands"].values()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if differences:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
