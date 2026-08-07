from datetime import datetime, timezone

from app.models.cleanroom_v1 import GeoEvidence, GeoQuestionPlan, GeoWorkspace
from app.v1.competitor_comparison import build_competitor_comparison, brand_configs
from app.v1.evidence_analysis import analyze_brand_status, find_brand_mentions
from app.v1.schemas import CompetitorComparisonRead


def evidence(evidence_id: int, answer: str, *, model_key: str = "deepseek") -> GeoEvidence:
    return GeoEvidence(
        id=evidence_id,
        workspace_id=1,
        run_id=evidence_id,
        question_plan_id=1,
        model_key=model_key,
        model_label="DeepSeek" if model_key == "deepseek" else "豆包",
        prompt_version="v1",
        sample_mode="api",
        evidence_level="auditable",
        collection_method="official_api_web_search",
        evidence_kind="provider_web_search",
        is_real_provider_evidence=True,
        brand_status="absent",
        answer_text=answer,
        answer_hash=str(evidence_id).zfill(64),
        source_items=[],
        sampling_environment={},
        captured_at=datetime(2026, 8, evidence_id, tzinfo=timezone.utc),
    )


def workspace() -> GeoWorkspace:
    return GeoWorkspace(
        id=1,
        company_id=1,
        slug="spring-yuan",
        brand_name="春秋元泉",
        brand_aliases=["Token统一管控平台"],
        status="active",
    )


def question() -> GeoQuestionPlan:
    return GeoQuestionPlan(
        id=1,
        workspace_id=1,
        question_text="企业应该如何选择 AI Token 管控平台？",
        journey_stage="decision",
        importance=5,
        is_brand_query=False,
        active=True,
        prompt_version="v1",
    )


def test_alias_matching_handles_nfkc_case_spaces_longest_and_boundaries() -> None:
    qax = find_brand_mentions("ＱＡＸ　ＡＩ安全网关与 VKEY", ["QAX AI安全网关", "vKey"])
    raytoken = find_brand_mentions("ray token 不等于 RayToken AI安全网关", ["RayToken", "RayToken AI安全网关"])

    assert [item.alias for item in qax] == ["QAX AI安全网关", "vKey"]
    assert [item.alias for item in raytoken] == ["RayToken", "RayToken AI安全网关"]
    assert find_brand_mentions("SAIGateway 与 AIGateway", ["AIGate"]) == []
    assert len(find_brand_mentions("AIGATE 和 aigate", ["AIGate"])) == 2


def test_workspace_catalog_does_not_match_generic_terms() -> None:
    aliases = [alias for config in brand_configs(workspace()) for alias in config.aliases]

    assert find_brand_mentions("这里只讨论 AI网关 和 Token平台，不点名任何品牌。", aliases) == []


def test_generic_product_term_is_not_a_baseline_brand_alias() -> None:
    result = build_competitor_comparison(
        workspace(),
        [evidence(1, "Token统一管控平台可以集中管理多模型密钥。")],
        [question()],
    )
    baseline = next(item for item in result["brands"] if item["is_baseline"])

    assert baseline["hit_answer_count"] == 0
    assert baseline["mention_rate"] == 0.0
    assert baseline["evidence"] == []


def test_comparison_deduplicates_aliases_and_keeps_zero_brands() -> None:
    result = build_competitor_comparison(
        workspace(),
        [
            evidence(1, "1. 春秋元泉（智能永信）\n2. 阿里云AI网关"),
            evidence(2, "不推荐奇安信 AI Gateway，建议选择腾讯云 LLM Security Gateway", model_key="doubao"),
        ],
        [question()],
    )
    brands = {item["key"]: item for item in result["brands"]}

    assert brands["chunqiu-yuanquan"]["hit_answer_count"] == 1
    assert brands["chunqiu-yuanquan"]["evidence"][0]["match_count"] == 2
    assert brands["chunqiu-yuanquan"]["average_first_appearance_order"] == 1
    assert brands["aliyun-ai-gateway"]["average_first_appearance_order"] == 2
    assert brands["qax-ai-gateway"]["negative_count"] == 1
    assert brands["tencent-ai-agent-security-gateway"]["recommendation_count"] == 1
    assert brands["raytoken"]["hit_answer_count"] == 0
    assert brands["aigate"]["evidence"] == []
    assert result["summary"]["answer_count"] == 2
    assert len(result["by_model"]) == 2
    assert len(result["by_question"]) == 1


def test_primary_brand_regression_keeps_existing_deterministic_outcomes() -> None:
    names = ["Token统一管控平台", "智能永信", "ichunqiu", "icqtoken"]

    assert analyze_brand_status("没有品牌", [], "春秋元泉", names) == ("absent", None)
    assert analyze_brand_status("不推荐春秋元泉", [], "春秋元泉", names) == ("negative", None)
    assert analyze_brand_status("推荐春秋元泉", [], "春秋元泉", names) == ("recommended", None)
    assert analyze_brand_status("1. 春秋元泉", [], "春秋元泉", names) == ("shortlisted", 1)


def test_explicit_ranked_competitor_ahead_counts_as_win() -> None:
    result = build_competitor_comparison(
        workspace(),
        [evidence(1, "1. 阿里云AI网关\n2. 春秋元泉")],
        [question()],
    )
    brands = {item["key"]: item for item in result["brands"]}
    aliyun = brands["aliyun-ai-gateway"]

    assert aliyun["wins_over_baseline"] == 1
    assert aliyun["comparable_answers"] == 1
    assert aliyun["top3_count"] == 1
    assert aliyun["top3_rate"] == 100.0
    assert aliyun["explicit_average_position"] == 1.0
    assert aliyun["win_reason_counts"] == {"explicit_rank_ahead": 1}
    assert aliyun["win_evidence"][0]["win_reason_type"] == "explicit_rank_ahead"
    assert aliyun["win_evidence"][0]["explicit_rank"] == 1
    assert aliyun["win_evidence"][0]["baseline_explicit_rank"] == 2
    assert result["summary"]["answers_where_competitor_wins"] == 1
    assert result["summary"]["comparable_answer_count"] == 1


def test_later_recommendation_does_not_override_earlier_explicit_rank() -> None:
    result = build_competitor_comparison(
        workspace(),
        [evidence(1, "1. 阿里云AI网关\n2. 春秋元泉\n随后推荐阿里云AI网关。")],
        [question()],
    )
    aliyun = next(item for item in result["brands"] if item["key"] == "aliyun-ai-gateway")

    assert aliyun["wins_over_baseline"] == 1
    assert aliyun["explicit_average_position"] == 1.0
    assert aliyun["win_evidence"][0]["explicit_rank"] == 1
    assert aliyun["win_evidence"][0]["baseline_explicit_rank"] == 2


def test_shortlisted_competitor_with_absent_baseline_counts_as_win() -> None:
    result = build_competitor_comparison(
        workspace(),
        [evidence(1, "候选方案：推荐阿里云AI网关用于统一密钥管理。")],
        [question()],
    )
    aliyun = next(item for item in result["brands"] if item["key"] == "aliyun-ai-gateway")

    assert aliyun["wins_over_baseline"] == 1
    assert aliyun["comparable_answers"] == 1
    assert aliyun["win_reason_counts"] == {"selected_baseline_absent": 1}
    assert aliyun["win_evidence"][0]["win_reason_type"] == "selected_baseline_absent"
    assert aliyun["win_evidence"][0]["baseline_explicit_rank"] is None


def test_named_representative_with_absent_baseline_counts_as_selected_win() -> None:
    result = build_competitor_comparison(
        workspace(),
        [evidence(1, "商业聚合平台的典型代表：阿里云AI网关、其他云平台。")],
        [question()],
    )
    aliyun = next(item for item in result["brands"] if item["key"] == "aliyun-ai-gateway")

    assert aliyun["candidate_count"] == 1
    assert aliyun["wins_over_baseline"] == 1
    assert aliyun["win_reason_counts"] == {"selected_baseline_absent": 1}


def test_paragraph_appearance_without_explicit_rank_does_not_count_as_win() -> None:
    result = build_competitor_comparison(
        workspace(),
        [evidence(1, "阿里云AI网关提供云上能力。春秋元泉支持企业统一治理。")],
        [question()],
    )
    aliyun = next(item for item in result["brands"] if item["key"] == "aliyun-ai-gateway")

    assert aliyun["wins_over_baseline"] == 0
    assert aliyun["comparable_answers"] == 0
    assert aliyun["win_evidence"] == []
    assert aliyun["average_first_appearance_order"] == 1
    assert aliyun["explicit_average_position"] is None
    assert result["summary"]["answers_where_competitor_wins"] == 0


def test_markdown_table_order_is_an_explicit_rank_and_supports_top3() -> None:
    answer = """| 平台 | 特点 |
| --- | --- |
| 阿里云AI网关 | 云上集成 |
| 春秋元泉 | 企业统一治理 |"""
    result = build_competitor_comparison(workspace(), [evidence(1, answer)], [question()])
    brands = {item["key"]: item for item in result["brands"]}

    assert brands["aliyun-ai-gateway"]["explicit_average_position"] == 1.0
    assert brands["chunqiu-yuanquan"]["explicit_average_position"] == 2.0
    assert brands["aliyun-ai-gateway"]["wins_over_baseline"] == 1
    assert brands["aliyun-ai-gateway"]["top3_count"] == 1


def test_action_diagnostic_is_deterministic_and_links_real_win_evidence() -> None:
    result = build_competitor_comparison(
        workspace(),
        [
            evidence(1, "推荐阿里云AI网关作为候选方案。"),
            evidence(2, "春秋元泉提供企业统一治理。"),
        ],
        [question()],
    )

    assert result["action_diagnostics"] == [
        {
            "competitor_key": "aliyun-ai-gateway",
            "competitor_name": "阿里云 AI网关",
            "model_key": "deepseek",
            "model_label": "DeepSeek",
            "question_plan_id": 1,
            "question": "企业应该如何选择 AI Token 管控平台？",
            "competitor_hit_count": 1,
            "baseline_hit_count": 1,
            "mention_gap": 0,
            "wins_over_baseline": 1,
            "comparable_answers": 1,
            "reason_type": "selected_baseline_absent",
            "reason_label": "竞品入选而春秋元泉缺席",
            "evidence_count": 1,
            "evidence_ids": [1],
            "evidence": result["action_diagnostics"][0]["evidence"],
            "suggestion": "建议：优先补齐该采购问题的可引用产品内容，再复测 DeepSeek。",
            "suggestion_type": "fill_citable_content_then_retest",
        }
    ]
    assert result["action_diagnostics"][0]["evidence"][0]["evidence_id"] == 1
    assert result["action_diagnostics"][0]["evidence"][0]["win_reason_type"] == (
        "selected_baseline_absent"
    )


def test_http_response_schema_preserves_comparison_and_diagnostic_fields() -> None:
    subject = workspace()
    result = build_competitor_comparison(
        subject,
        [evidence(1, "1. 阿里云AI网关\n2. 春秋元泉")],
        [question()],
    )
    response = CompetitorComparisonRead.model_validate({
        "workspace": subject,
        "scope": {"real_provider_evidence_only": True},
        **result,
        "available_models": [{"key": "deepseek", "label": "DeepSeek"}],
        "available_questions": [question()],
    }).model_dump()

    assert response["summary"]["answers_where_competitor_wins"] == 1
    aliyun = next(item for item in response["brands"] if item["key"] == "aliyun-ai-gateway")
    assert aliyun["wins_over_baseline"] == 1
    assert aliyun["win_evidence"][0]["win_reason_type"] == "explicit_rank_ahead"
    assert response["action_diagnostics"][0]["evidence_ids"] == [1]
