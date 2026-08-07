"""Read-only deterministic comparison over archived real GEO answers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
import re
import unicodedata

from app.models.cleanroom_v1 import GeoEvidence, GeoQuestionPlan, GeoWorkspace
from app.v1.evidence_analysis import BrandTextMatch, find_brand_mentions


MATCH_RULE_VERSION = "competitor-comparison-v1.2"

NEGATIVE_MARKERS = (
    "不推荐", "不建议", "不是首选", "非首选", "未推荐", "没有推荐",
    "不列入候选", "未列入候选", "未进入候选", "没有提及", "未提及", "不引用",
)
RECOMMENDATION_MARKERS = ("推荐", "首选", "优先", "建议选择", "值得考虑")
CANDIDATE_MARKERS = (
    "候选", "入选", "备选", "推荐", "首选", "优先",
    "典型代表", "代表产品", "代表平台", "代表",
)


@dataclass(frozen=True)
class BrandConfig:
    key: str
    canonical_name: str
    aliases: tuple[str, ...]
    is_baseline: bool = False


WORKSPACE_DEFAULTS: dict[int, tuple[BrandConfig, ...]] = {
    1: (
        BrandConfig(
            "chunqiu-yuanquan",
            "春秋元泉",
            ("春秋元泉", "智能永信", "ichunqiu", "icqtoken"),
            True,
        ),
        BrandConfig(
            "raytoken",
            "RayToken",
            ("RayToken", "RayToken AI安全网关", "盛邦安全 AI安全网关", "WebRAY AI安全网关"),
        ),
        BrandConfig(
            "qax-ai-gateway",
            "奇安信 AI安全网关",
            ("奇安信AI安全网关", "QAX AI安全网关", "奇安信 AI Gateway", "vKey"),
        ),
        BrandConfig(
            "aigate",
            "AIGate",
            ("AIGate", "Enterprise AI Gateway", "企业 AI Token 统一管理", "万根 AI 网关"),
        ),
        BrandConfig(
            "aliyun-ai-gateway",
            "阿里云 AI网关",
            ("阿里云AI网关", "Aliyun AI Gateway", "API Gateway AI网关"),
        ),
        BrandConfig(
            "tencent-ai-agent-security-gateway",
            "腾讯云 AI Agent安全网关",
            ("腾讯云AI Agent安全网关", "AI Agent安全网关", "腾讯云 LLM Security Gateway"),
        ),
    ),
}


def brand_configs(workspace: GeoWorkspace) -> tuple[BrandConfig, ...]:
    configured = WORKSPACE_DEFAULTS.get(workspace.id)
    if configured:
        return configured
    aliases = tuple(dict.fromkeys([workspace.brand_name, *(workspace.brand_aliases or [])]))
    return (BrandConfig("workspace-brand", workspace.brand_name, aliases, True),)


WIN_REASON_LABELS = {
    "explicit_rank_ahead": "明确排序在春秋元泉之前",
    "selected_baseline_absent": "竞品入选而春秋元泉缺席",
}


def _table_position(answer: str, match: BrandTextMatch) -> int | None:
    normalized = unicodedata.normalize("NFKC", answer)
    lines = normalized.splitlines(keepends=True)
    offset = 0
    matched_line_index = -1
    for index, line in enumerate(lines):
        if offset <= match.start < offset + len(line):
            matched_line_index = index
            break
        offset += len(line)
    if matched_line_index < 0:
        return None

    line = lines[matched_line_index].strip()
    if "|" in line:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 2:
            numeric_rank = re.match(r"^(\d{1,2})$", cells[0])
            if numeric_rank:
                return int(numeric_rank.group(1))
            separator_index = next(
                (
                    index
                    for index in range(matched_line_index - 1, -1, -1)
                    if re.match(r"^\s*\|?\s*:?-{3,}", lines[index])
                ),
                None,
            )
            if separator_index is not None:
                data_rows = [
                    row
                    for row in lines[separator_index + 1:matched_line_index + 1]
                    if "|" in row and row.strip(" |\r\n")
                ]
                return len(data_rows) or None

    if "\t" in line:
        cells = [cell.strip() for cell in line.split("\t")]
        numeric_rank = re.match(r"^(\d{1,2})$", cells[0]) if cells else None
        if numeric_rank:
            return int(numeric_rank.group(1))
        header_index = next(
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
        if header_index is not None:
            data_rows = [
                row
                for row in lines[header_index + 1:matched_line_index + 1]
                if "\t" in row and row.strip()
            ]
            return len(data_rows) or None
    return None


def _explicit_position(answer: str, match: BrandTextMatch) -> int | None:
    normalized = unicodedata.normalize("NFKC", answer)
    line_start = normalized.rfind("\n", 0, match.start) + 1
    line_end = normalized.find("\n", match.end)
    line = normalized[line_start:line_end if line_end >= 0 else len(normalized)].strip()
    numbered = re.match(r"^(?:#{1,6}\s*)?(\d{1,2})[.、)]\s*", line)
    if numbered:
        return int(numbered.group(1))
    return _table_position(answer, match)


def _context(answer: str, match: BrandTextMatch, window: int = 105) -> str:
    normalized = unicodedata.normalize("NFKC", answer)
    excerpt = normalized[max(0, match.start - window):min(len(normalized), match.end + window)]
    return re.sub(r"\s+", " ", excerpt).strip()


def _classification(answer: str, match: BrandTextMatch) -> tuple[str, int | None]:
    normalized = unicodedata.normalize("NFKC", answer)
    context_start = max(0, match.start - 55)
    context_end = min(len(normalized), match.end + 55)
    context = normalized[context_start:context_end].casefold()
    relative_start = match.start - context_start
    relative_end = match.end - context_start

    def marker_distance(markers: tuple[str, ...]) -> int | None:
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

    negative_distance = marker_distance(NEGATIVE_MARKERS)
    recommendation_distance = marker_distance(RECOMMENDATION_MARKERS)
    candidate_distance = marker_distance(CANDIDATE_MARKERS)
    position = _explicit_position(answer, match)
    if negative_distance is not None and negative_distance <= 24 and (
        recommendation_distance is None or negative_distance <= recommendation_distance
    ):
        return "negative", position
    if recommendation_distance is not None and recommendation_distance <= 24:
        return "recommended", position
    if position is not None or (candidate_distance is not None and candidate_distance <= 24):
        return "shortlisted", position
    return "mentioned", position


def _analyze_answer(
    evidence: GeoEvidence,
    questions: dict[int, GeoQuestionPlan],
    configs: tuple[BrandConfig, ...],
) -> dict:
    hits: dict[str, dict] = {}
    for config in configs:
        matches = find_brand_mentions(evidence.answer_text, list(config.aliases))
        if not matches:
            continue
        first = matches[0]
        classified = [(*_classification(evidence.answer_text, match), match) for match in matches]
        priority = {"negative": 0, "recommended": 1, "shortlisted": 2, "mentioned": 3}
        status, _, strongest_match = min(
            classified,
            key=lambda item: (priority[item[0]], item[2].start),
        )
        explicit_matches = [item for item in classified if item[1] is not None]
        explicit_position = min((item[1] for item in explicit_matches), default=None)
        hits[config.key] = {
            "matches": matches,
            "first_start": first.start,
            "matched_aliases": list(dict.fromkeys(match.alias for match in matches)),
            "status": status,
            "explicit_position": explicit_position,
            "context_snippet": _context(evidence.answer_text, strongest_match),
        }
    ordered = sorted(hits, key=lambda key: (hits[key]["first_start"], key))
    for index, key in enumerate(ordered, 1):
        hits[key]["appearance_order"] = index
    baseline_key = next(config.key for config in configs if config.is_baseline)
    baseline_hit = hits.get(baseline_key)
    comparisons: dict[str, dict] = {}
    for config in configs:
        if config.is_baseline:
            continue
        competitor_hit = hits.get(config.key)
        comparable = False
        winner = False
        reason_type = None
        if competitor_hit and baseline_hit:
            competitor_rank = competitor_hit["explicit_position"]
            baseline_rank = baseline_hit["explicit_position"]
            comparable = competitor_rank is not None and baseline_rank is not None
            if comparable and competitor_rank < baseline_rank:
                winner = True
                reason_type = "explicit_rank_ahead"
        elif competitor_hit and not baseline_hit:
            comparable = competitor_hit["status"] in {"shortlisted", "recommended"}
            if comparable:
                winner = True
                reason_type = "selected_baseline_absent"
        elif baseline_hit and not competitor_hit:
            comparable = baseline_hit["status"] in {"shortlisted", "recommended"}
        comparisons[config.key] = {
            "comparable": comparable,
            "winner": winner,
            "reason_type": reason_type,
        }
    return {
        "evidence": evidence,
        "question": questions.get(evidence.question_plan_id),
        "hits": hits,
        "matched_brand_keys": ordered,
        "comparisons": comparisons,
    }


def _evidence_payload(
    analysis: dict,
    config: BrandConfig,
    baseline_key: str,
) -> dict:
    evidence = analysis["evidence"]
    hit = analysis["hits"][config.key]
    comparison = analysis["comparisons"].get(config.key, {})
    baseline_hit = analysis["hits"].get(baseline_key)
    return {
        "evidence_id": evidence.id,
        "question_plan_id": evidence.question_plan_id,
        "question": analysis["question"].question_text if analysis["question"] else "未知问题",
        "model_key": evidence.model_key,
        "model_label": evidence.model_label,
        "brand_key": config.key,
        "brand_name": config.canonical_name,
        "matched_brand_keys": analysis["matched_brand_keys"],
        "matched_aliases": hit["matched_aliases"],
        "match_count": len(hit["matches"]),
        "status": hit["status"],
        "appearance_order": hit["appearance_order"],
        "explicit_list_position": hit["explicit_position"],
        "explicit_rank": hit["explicit_position"],
        "baseline_explicit_rank": (
            baseline_hit["explicit_position"] if baseline_hit is not None else None
        ),
        "comparison_result": "win" if comparison.get("winner") else (
            "comparable" if comparison.get("comparable") else "not_comparable"
        ),
        "win_reason_type": comparison.get("reason_type"),
        "context_snippet": hit["context_snippet"],
        "captured_at": evidence.captured_at,
    }


def _brand_stats(
    analyses: list[dict],
    configs: tuple[BrandConfig, ...],
    denominator: int,
    evidence_limit: int,
) -> list[dict]:
    rows: list[dict] = []
    baseline_key = next(config.key for config in configs if config.is_baseline)
    for config in configs:
        matched = [analysis for analysis in analyses if config.key in analysis["hits"]]
        questions = {analysis["evidence"].question_plan_id for analysis in matched}
        models = {analysis["evidence"].model_key for analysis in matched}
        orders = [analysis["hits"][config.key]["appearance_order"] for analysis in matched]
        explicit_positions = [
            analysis["hits"][config.key]["explicit_position"]
            for analysis in matched
            if analysis["hits"][config.key]["explicit_position"] is not None
        ]
        evidence_rows: list[dict] = []
        for analysis in sorted(
            matched,
            key=lambda item: (item["evidence"].captured_at, item["evidence"].id),
            reverse=True,
        )[:evidence_limit]:
            evidence_rows.append(_evidence_payload(analysis, config, baseline_key))
        status_counts = defaultdict(int)
        for analysis in matched:
            status_counts[analysis["hits"][config.key]["status"]] += 1
        comparisons = [] if config.is_baseline else [
            analysis["comparisons"][config.key] for analysis in analyses
        ]
        win_analyses = [] if config.is_baseline else [
            analysis
            for analysis in analyses
            if analysis["comparisons"][config.key]["winner"]
        ]
        reason_counts: dict[str, int] = defaultdict(int)
        for analysis in win_analyses:
            reason_counts[analysis["comparisons"][config.key]["reason_type"]] += 1
        win_evidence = [
            _evidence_payload(analysis, config, baseline_key)
            for analysis in sorted(
                win_analyses,
                key=lambda item: (item["evidence"].captured_at, item["evidence"].id),
                reverse=True,
            )[:evidence_limit]
        ]
        top3_count = sum(position <= 3 for position in explicit_positions)
        rows.append({
            "key": config.key,
            "canonical_name": config.canonical_name,
            "aliases": list(config.aliases),
            "is_baseline": config.is_baseline,
            "hit_answer_count": len(matched),
            "mention_rate": round(len(matched) / denominator * 100, 1) if denominator else 0.0,
            "question_count": len(questions),
            "model_count": len(models),
            "candidate_count": status_counts["shortlisted"] + status_counts["recommended"],
            "recommendation_count": status_counts["recommended"],
            "negative_count": status_counts["negative"],
            "average_first_appearance_order": round(mean(orders), 2) if orders else None,
            "order_observation_count": len(orders),
            "wins_over_baseline": len(win_analyses),
            "comparable_answers": sum(item["comparable"] for item in comparisons),
            "top3_count": top3_count,
            "top3_rate": (
                round(top3_count / len(explicit_positions) * 100, 1)
                if explicit_positions else 0.0
            ),
            "explicit_average_position": (
                round(mean(explicit_positions), 2) if explicit_positions else None
            ),
            "explicit_rank_observation_count": len(explicit_positions),
            "win_reason_counts": dict(reason_counts),
            "win_evidence": win_evidence,
            "evidence_total": len(matched),
            "evidence": evidence_rows,
        })
    rows.sort(
        key=lambda item: (
            0 if item["is_baseline"] else 1,
            -item["wins_over_baseline"],
            -item["hit_answer_count"],
            item["canonical_name"],
        )
    )
    return rows


def _action_diagnostics(
    analyses: list[dict],
    configs: tuple[BrandConfig, ...],
    limit: int = 3,
) -> list[dict]:
    baseline = next(config for config in configs if config.is_baseline)
    config_by_key = {config.key: config for config in configs}
    grouped_wins: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for analysis in analyses:
        evidence = analysis["evidence"]
        for competitor_key, comparison in analysis["comparisons"].items():
            if comparison["winner"]:
                grouped_wins[(competitor_key, evidence.model_key, evidence.question_plan_id)].append(
                    analysis
                )

    diagnostics: list[dict] = []
    for (competitor_key, model_key, question_id), wins in grouped_wins.items():
        competitor = config_by_key[competitor_key]
        scoped = [
            analysis
            for analysis in analyses
            if analysis["evidence"].model_key == model_key
            and analysis["evidence"].question_plan_id == question_id
        ]
        competitor_hits = sum(competitor_key in analysis["hits"] for analysis in scoped)
        baseline_hits = sum(baseline.key in analysis["hits"] for analysis in scoped)
        reason_counts: dict[str, int] = defaultdict(int)
        for analysis in wins:
            reason_counts[analysis["comparisons"][competitor_key]["reason_type"]] += 1
        reason_type = sorted(
            reason_counts,
            key=lambda key: (-reason_counts[key], 0 if key == "explicit_rank_ahead" else 1),
        )[0]
        model_label = wins[0]["evidence"].model_label
        if reason_type == "explicit_rank_ahead":
            suggestion = (
                f"建议：核对该问题的功能证据与对比材料，补齐后复测 {model_label}。"
            )
            suggestion_type = "strengthen_comparison_evidence_then_retest"
        else:
            suggestion = f"建议：优先补齐该采购问题的可引用产品内容，再复测 {model_label}。"
            suggestion_type = "fill_citable_content_then_retest"
        ordered_wins = sorted(
            wins,
            key=lambda item: (item["evidence"].captured_at, item["evidence"].id),
            reverse=True,
        )
        diagnostics.append({
            "competitor_key": competitor_key,
            "competitor_name": competitor.canonical_name,
            "model_key": model_key,
            "model_label": model_label,
            "question_plan_id": question_id,
            "question": (
                wins[0]["question"].question_text if wins[0]["question"] else "未知问题"
            ),
            "competitor_hit_count": competitor_hits,
            "baseline_hit_count": baseline_hits,
            "mention_gap": competitor_hits - baseline_hits,
            "wins_over_baseline": len(wins),
            "comparable_answers": sum(
                analysis["comparisons"][competitor_key]["comparable"] for analysis in scoped
            ),
            "reason_type": reason_type,
            "reason_label": WIN_REASON_LABELS[reason_type],
            "evidence_count": len(wins),
            "evidence_ids": [analysis["evidence"].id for analysis in ordered_wins],
            "evidence": [
                _evidence_payload(analysis, competitor, baseline.key)
                for analysis in ordered_wins
            ],
            "suggestion": suggestion,
            "suggestion_type": suggestion_type,
        })
    diagnostics.sort(
        key=lambda item: (
            -item["wins_over_baseline"],
            -item["mention_gap"],
            item["competitor_name"],
            item["model_label"],
            item["question_plan_id"],
        )
    )
    return diagnostics[:limit]


def build_competitor_comparison(
    workspace: GeoWorkspace,
    evidence_rows: list[GeoEvidence],
    question_rows: list[GeoQuestionPlan],
    *,
    excluded_non_real_answer_count: int = 0,
    evidence_limit: int = 50,
) -> dict:
    configs = brand_configs(workspace)
    questions = {row.id: row for row in question_rows}
    analyses = [_analyze_answer(row, questions, configs) for row in evidence_rows]
    overall = _brand_stats(analyses, configs, len(analyses), evidence_limit)

    by_model = []
    model_groups: dict[str, list[dict]] = defaultdict(list)
    for analysis in analyses:
        model_groups[analysis["evidence"].model_key].append(analysis)
    for key, group in sorted(model_groups.items(), key=lambda item: item[1][0]["evidence"].model_label):
        by_model.append({
            "key": key,
            "label": group[0]["evidence"].model_label,
            "answer_count": len(group),
            "brands": _brand_stats(group, configs, len(group), 0),
        })

    by_question = []
    question_groups: dict[int, list[dict]] = defaultdict(list)
    for analysis in analyses:
        question_groups[analysis["evidence"].question_plan_id].append(analysis)
    for question_id, group in sorted(question_groups.items()):
        question = questions.get(question_id)
        by_question.append({
            "id": question_id,
            "label": question.question_text if question else "未知问题",
            "answer_count": len(group),
            "brands": _brand_stats(group, configs, len(group), 0),
        })

    comparable_answers = sum(
        any(comparison["comparable"] for comparison in analysis["comparisons"].values())
        for analysis in analyses
    )
    competitor_win_answers = sum(
        any(comparison["winner"] for comparison in analysis["comparisons"].values())
        for analysis in analyses
    )

    return {
        "summary": {
            "answer_count": len(analyses),
            "tracked_brand_count": len(configs),
            "answers_with_tracked_brand": sum(bool(item["hits"]) for item in analyses),
            "excluded_non_real_answer_count": excluded_non_real_answer_count,
            "comparable_answer_count": comparable_answers,
            "answers_where_competitor_wins": competitor_win_answers,
        },
        "brands": overall,
        "by_model": by_model,
        "by_question": by_question,
        "action_diagnostics": _action_diagnostics(analyses, configs),
        "matching_rule_version": MATCH_RULE_VERSION,
        "methodology": {
            "mention": "同一品牌多个别名在一条回答中去重，命中回答数按回答计数。",
            "candidate": "品牌出现在编号清单，或上下文含候选、入选、备选、推荐、首选、优先时计入。",
            "recommendation": "品牌附近上下文明确出现推荐、首选、优先、建议选择或值得考虑时计入。",
            "negative": "否定词优先于推荐词；不推荐、不建议、非首选等上下文计入负面。",
            "appearance_order": "同一回答内品牌首次出现的文本顺序，仅用于定位，绝不作为排名或胜负依据。",
            "explicit_rank": "只认编号列表或可识别表格的数据行顺序；同一品牌保留最靠前的明确排名，Top 3 与平均位置只使用该字段。",
            "win": "同一回答中，竞品明确排名在春秋元泉之前；或竞品进入候选/推荐而春秋元泉缺席，才计为胜出。后续推荐文本不会覆盖更早的明确排名。",
            "comparable": "双方都有明确排名，或一方进入候选/推荐而另一方缺席，才计为可比较回答。",
            "diagnostic": "行动诊断按竞品、模型、问题聚合真实胜出证据；建议由胜出类型固定映射，不是模型原话。",
            "denominator": "提及率分母是当前筛选范围内已解析的真实回答数；同一回答内同一品牌多个别名只计 1 条。模型/问题分组各自使用本组回答数，不按调用次数隐式加权。",
            "zero_and_small_samples": "0 命中品牌保留为 0；无明确排名时平均位置为 null。指标不把段落出现顺序当排名，也不为零样本伪造统计精度。",
        },
    }
