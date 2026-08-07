from datetime import datetime, timedelta, timezone

from app.models.cleanroom_v1 import GeoEvidence, GeoQuestionPlan, GeoWorkspace
from app.v1.question_analysis import build_question_analysis


def _question() -> GeoQuestionPlan:
    return GeoQuestionPlan(
        id=1,
        workspace_id=1,
        question_text="企业级模型治理平台怎么选？",
        journey_stage="consideration",
        role="technical_lead",
        topic_tags=["治理"],
        importance=4,
        is_brand_query=False,
        active=True,
        status="active",
        source_type="manual",
        source_evidence={},
        version=1,
        template_variables=[],
        prompt_version="v1",
    )


def _evidence(evidence_id: int, run_id: int, captured_at: datetime, answer: str, status: str) -> GeoEvidence:
    return GeoEvidence(
        id=evidence_id,
        workspace_id=1,
        run_id=run_id,
        question_plan_id=1,
        model_key="deepseek",
        model_label="DeepSeek",
        prompt_version="v1",
        sample_mode="authorized_api",
        evidence_level="auditable",
        collection_method="official_api_web_search",
        evidence_kind="answer",
        is_real_provider_evidence=True,
        brand_status=status,
        brand_position=2 if status != "absent" else None,
        competitor_positions=[],
        answer_text=answer,
        answer_hash=f"{evidence_id:064d}",
        source_items=[{"url": "https://source.example.com/guide", "title": "采购指南"}],
        sampling_environment={},
        captured_at=captured_at,
    )


def test_question_analysis_is_scoped_to_latest_run_and_explains_delta() -> None:
    now = datetime.now(timezone.utc)
    rows = [
        _evidence(1, 10, now, "1. RayToken\n2. 春秋元泉", "mentioned"),
        _evidence(2, 9, now - timedelta(days=2), "没有提及春秋元泉", "absent"),
    ]
    result = build_question_analysis(
        GeoWorkspace(
            id=1,
            company_id=1,
            slug="yuanquan",
            brand_name="春秋元泉",
            brand_aliases=[],
        ),
        _question(),
        rows,
        scope="current",
        period_days=None,
        now=now,
    )

    assert result["scope"]["current_run_ids"] == [10]
    assert result["summary"]["answer_count"] == 1
    assert result["comparison"]["previous"]["answer_count"] == 1
    assert result["comparison"]["delta"]["mention_rate"] == 100.0
    assert result["sources"][0]["domain"] == "source.example.com"
