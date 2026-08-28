from datetime import datetime, timezone

from app.models.cleanroom_v1 import GeoEvidence, GeoQuestionPlan
from app.v1.source_map import build_source_map, normalize_source_url


def evidence(
    evidence_id: int,
    *,
    model_key: str,
    model_label: str,
    brand_status: str,
    source_items: list[dict],
) -> GeoEvidence:
    return GeoEvidence(
        id=evidence_id,
        workspace_id=1,
        run_id=evidence_id,
        question_plan_id=1,
        model_key=model_key,
        model_label=model_label,
        prompt_version="v1",
        sample_mode="api",
        evidence_level="auditable",
        collection_method="official_api_web_search",
        evidence_kind="provider_web_search",
        is_real_provider_evidence=True,
        brand_status=brand_status,
        answer_text="answer",
        answer_hash=str(evidence_id).zfill(64),
        source_items=source_items,
        sampling_environment={},
        captured_at=datetime(2026, 8, evidence_id, tzinfo=timezone.utc),
    )


def test_normalize_source_url_handles_scheme_www_slash_query_and_fragment() -> None:
    first = normalize_source_url("https://www.Example.com:443/path/?b=2&a=1#fragment")
    second = normalize_source_url("http://example.com/path?a=1&b=2")

    assert first is not None
    assert second is not None
    assert first.domain == "example.com"
    assert first.page_key == second.page_key == "example.com/path?a=1&b=2"
    assert normalize_source_url("mailto:hello@example.com") is None
    assert normalize_source_url("https://localhost/path") is None


def test_build_source_map_deduplicates_per_answer_and_keeps_traceability() -> None:
    question = GeoQuestionPlan(
        id=1,
        workspace_id=1,
        question_text="企业应该如何选择 GEO 服务？",
        journey_stage="decision",
        importance=5,
        is_brand_query=False,
        active=True,
        prompt_version="v1",
    )
    rows = [
        evidence(
            1,
            model_key="deepseek",
            model_label="DeepSeek",
            brand_status="absent",
            source_items=[
                {"url": "https://www.example.com/a/", "title": "A"},
                {"url": "http://example.com/a", "title": "duplicate"},
                {"url": "https://example.com/b", "title": "B"},
                {"url": "not a url", "title": "invalid"},
            ],
        ),
        evidence(
            2,
            model_key="qianwen",
            model_label="通义千问",
            brand_status="cited",
            source_items=[{"url": "https://example.com/a", "title": "A"}],
        ),
    ]

    result = build_source_map(rows, [question], limit=10, evidence_limit=1)

    assert result["summary"] == {
        "answer_count": 2,
        "answers_with_sources": 2,
        "citation_count": 3,
        "unique_domain_count": 1,
        "unique_page_count": 2,
        "brand_absent_answer_count": 1,
        "brand_absent_answer_ratio": 50.0,
        "ignored_source_count": 1,
        "duplicate_source_count": 1,
        "excluded_non_real_answer_count": 0,
    }
    domain = result["domains"][0]
    assert domain["citation_count"] == 3
    assert domain["answer_count"] == 2
    assert domain["model_count"] == 2
    assert domain["brand_absent_answer_count"] == 1
    assert domain["evidence_ids"] == [2]
    assert domain["evidence_references"] == [
        {
            "evidence_id": 2,
            "source_url": "https://example.com/a",
            "source_title": "A",
        }
    ]
    assert domain["evidence_total"] == 2
    assert domain["evidence_truncated"] is True
    assert domain["influence_score"] == 100
    assert domain["tier"] == "core"
    assert domain["score_factors"] == {
        "citation_frequency": 35,
        "answer_reach": 25,
        "model_breadth": 20,
        "question_breadth": 20,
    }
    assert result["opportunities"][0]["label"] == "example.com"


def test_source_map_caps_single_answer_and_explains_relations() -> None:
    question = GeoQuestionPlan(
        id=1,
        workspace_id=1,
        question_text="企业应该如何选择 GEO 服务？",
        journey_stage="decision",
        importance=5,
        is_brand_query=False,
        active=True,
        prompt_version="v1",
    )
    rows = [
        evidence(
            1,
            model_key="deepseek",
            model_label="DeepSeek",
            brand_status="absent",
            source_items=[
                {"url": "https://alpha.example/a"},
                {"url": "https://beta.example/b"},
            ],
        )
    ]

    result = build_source_map(rows, [question], limit=10, evidence_limit=10)

    assert all(item["influence_score"] == 29 for item in result["domains"])
    assert all(item["tier"] == "unverified" for item in result["domains"])
    relation = result["domains"][0]["related_sources"][0]
    assert relation["shared_answer_count"] == 1
    assert relation["shared_model_count"] == 1
    assert relation["shared_question_count"] == 1
    assert relation["strength"] == "weak"
