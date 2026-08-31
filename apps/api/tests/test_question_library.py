from datetime import datetime, timezone
from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models.company import Company
from app.models.cleanroom_v1 import GeoQuestionPlan, GeoQuestionReview
from app.models.cleanroom_v1 import GeoWorkspace
from app.models.user import User
from app.services.workspace_access import add_membership
from app.v1.observation_service import question_sampling_eligible as _question_sampling_eligible


@pytest.fixture
def question_library_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="测试管理员", email="questions@example.com", role="company_admin"))
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="test-workspace",
                brand_name="测试品牌",
                brand_aliases=[],
            )
        )
        db.add_all(
            [
                GeoQuestionPlan(
                    id=1,
                    workspace_id=1,
                    question_text="如何配置审批安全策略？",
                    journey_stage="consideration",
                    role="technical_lead",
                    topic_tags=["审批", "安全"],
                    importance=4,
                    status="active",
                    source_type="manual",
                    source_evidence={},
                    version=1,
                    template_variables=[],
                    prompt_version="v1",
                ),
                GeoQuestionPlan(
                    id=2,
                    workspace_id=1,
                    question_text="如何做好成本预算？",
                    journey_stage="awareness",
                    role="procurement",
                    topic_tags=["成本"],
                    importance=3,
                    status="active",
                    source_type="manual",
                    source_evidence={},
                    version=1,
                    template_variables=[],
                    prompt_version="v1",
                ),
            ]
        )
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        db.commit()

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, company_id=1, role="company_admin"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_question_library_topic_filter_matches_each_tag_and_preserves_unfiltered_list(
    question_library_client: TestClient,
) -> None:
    client = question_library_client

    unfiltered = client.get("/api/v1/workspaces/1/question-library")
    assert unfiltered.status_code == 200
    assert {question["id"] for question in unfiltered.json()["questions"]} == {1, 2}

    first_tag = client.get("/api/v1/workspaces/1/question-library?topic=审批")
    assert first_tag.status_code == 200
    assert [question["id"] for question in first_tag.json()["questions"]] == [1]

    non_first_tag = client.get("/api/v1/workspaces/1/question-library?topic=安全")
    assert non_first_tag.status_code == 200
    assert [question["id"] for question in non_first_tag.json()["questions"]] == [1]

    unrelated_tag = client.get("/api/v1/workspaces/1/question-library?topic=不存在")
    assert unrelated_tag.status_code == 200
    assert unrelated_tag.json()["questions"] == []


def test_unapproved_question_is_not_sampling_eligible() -> None:
    pending = GeoQuestionPlan(
        id=1,
        workspace_id=1,
        question_text="如何评估 Token 管控方案？",
        journey_stage="consideration",
        role="technical_lead",
        topic_tags=["Token 管控"],
        importance=4,
        is_brand_query=False,
        active=True,
        status="pending_review",
        source_type="answer_gap",
        source_evidence={"evidence_id": 17},
        source_reason="真实回答中缺少成本边界",
        source_at=datetime.now(timezone.utc),
        version=1,
        template_variables=["品牌"],
        prompt_version="v1",
    )
    assert pending.status == "pending_review"
    assert pending.active is True
    assert pending.status not in {"approved", "active"}
    assert _question_sampling_eligible(pending) is False
    pending.status = "approved"
    assert _question_sampling_eligible(pending) is True


def test_question_review_keeps_source_and_snapshot_fields() -> None:
    review = GeoQuestionReview(
        workspace_id=1,
        question_plan_id=1,
        actor_user_id=2,
        action="approved",
        from_status="pending_review",
        to_status="approved",
        note="证据充分",
        snapshot={
            "source_type": "answer_gap",
            "source_evidence": {"evidence_id": 17},
            "version": 1,
        },
    )
    assert review.snapshot["source_evidence"]["evidence_id"] == 17
    assert review.to_status == "approved"
