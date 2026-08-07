"""Isolated API contract verification for the Spring Yuan GEO V1 loop."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[3]
    / ".ai-change"
    / "spring-yuan-geo-v1-rebuild"
    / "evidence"
    / "geo-v1-api-contract.json"
)


def _require(value: bool, message: str, detail: object | None = None) -> None:
    if not value:
        raise AssertionError(f"{message}: {detail!r}")


def _run() -> dict:
    from fastapi.testclient import TestClient

    from app import models  # noqa: F401
    from app.db.session import Base, SessionLocal, engine
    from app.main import app
    from app.models import AnswerAnalysis, CitationSource, Company, CrawlResult, CrawlTask, LLMProvider, Project, TargetQuestion, User
    from app.services.auth import hash_password

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        company = Company(name="春秋元泉", industry="企业 AI 安全", website_url="https://example.test", brand_aliases=["春秋元泉"], status="active")
        other_company = Company(name="隔离企业", status="active")
        db.add_all([company, other_company])
        db.flush()
        project = Project(company_id=company.id, name="春秋元泉 GEO V1", status="active")
        other_project = Project(company_id=other_company.id, name="隔离项目", status="active")
        user = User(company_id=None, name="V1 验收管理员", email="geo-v1@example.com", password_hash=hash_password("geo-v1-test"), role="super_admin", status="active")
        db.add_all([project, other_project, user])
        db.flush()
        organic_question = TargetQuestion(project_id=project.id, question_text="企业 AI 安全平台如何选择？", contains_brand=False, counts_for_visibility=True, journey_stage="consideration")
        brand_question = TargetQuestion(project_id=project.id, question_text="春秋元泉的服务能力有哪些？", contains_brand=True, counts_for_visibility=True, journey_stage="validation")
        other_question = TargetQuestion(project_id=other_project.id, question_text="隔离问题", contains_brand=False, counts_for_visibility=True)
        browser_provider = LLMProvider(name="网页端观测", provider_type="browser_observation", model_name="browser", status="active")
        mock_provider = LLMProvider(name="Mock 演示", provider_type="mock", model_name="mock", status="active")
        api_provider = LLMProvider(name="普通 API", provider_type="openai_compatible", model_name="fixture", api_base_url="https://fixture.invalid/v1", auth_config={"api_key": "fixture-not-a-secret"}, status="active")
        db.add_all([organic_question, brand_question, other_question, browser_provider, mock_provider, api_provider])
        db.flush()
        task = CrawlTask(project_id=project.id, provider_ids=[browser_provider.id], target_question_ids=[organic_question.id], status="success", started_at=datetime.now(UTC), finished_at=datetime.now(UTC))
        other_task = CrawlTask(project_id=other_project.id, provider_ids=[], target_question_ids=[other_question.id], status="success")
        db.add_all([task, other_task])
        db.flush()
        browser_result = CrawlResult(task_id=task.id, project_id=project.id, target_question_id=organic_question.id, provider_id=browser_provider.id, prompt_text=organic_question.question_text, raw_answer="春秋元泉值得纳入候选，详见官网。", answer_summary="网页端真实观测", status="success", collected_at=datetime.now(UTC))
        mock_result = CrawlResult(task_id=task.id, project_id=project.id, target_question_id=organic_question.id, provider_id=mock_provider.id, prompt_text=organic_question.question_text, raw_answer="Mock 提及春秋元泉", answer_summary="Mock", status="success", collected_at=datetime.now(UTC))
        branded_result = CrawlResult(task_id=task.id, project_id=project.id, target_question_id=brand_question.id, provider_id=api_provider.id, prompt_text=brand_question.question_text, raw_answer="春秋元泉事实待核验", answer_summary="品牌问题", status="success", collected_at=datetime.now(UTC))
        failed_result = CrawlResult(task_id=task.id, project_id=project.id, target_question_id=organic_question.id, provider_id=api_provider.id, prompt_text=organic_question.question_text, raw_answer="", answer_summary=None, status="failed", collected_at=datetime.now(UTC))
        other_result = CrawlResult(task_id=other_task.id, project_id=other_project.id, target_question_id=other_question.id, provider_id=None, prompt_text="隔离", raw_answer="隔离", status="success")
        db.add_all([browser_result, mock_result, branded_result, failed_result, other_result])
        db.flush()
        db.add_all([
            AnswerAnalysis(crawl_result_id=browser_result.id, company_mentioned=True, company_recommended=True, company_rank=1, sentiment="positive", confidence=80, analysis_json={}),
            AnswerAnalysis(crawl_result_id=mock_result.id, company_mentioned=True, company_recommended=True, company_rank=1, sentiment="positive", confidence=90, analysis_json={}),
            AnswerAnalysis(crawl_result_id=branded_result.id, company_mentioned=True, company_recommended=False, sentiment="neutral", confidence=70, analysis_json={}),
            CitationSource(crawl_result_id=browser_result.id, source_title="官网", source_url="https://example.test/evidence", source_domain="example.test", is_owned=True, is_placed=False),
        ])
        db.commit()
        ids = {"project": project.id, "organic_question": organic_question.id, "brand_question": brand_question.id, "browser_result": browser_result.id, "mock_result": mock_result.id, "branded_result": branded_result.id, "failed_result": failed_result.id, "other_result": other_result.id}

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": "geo-v1@example.com", "password": "geo-v1-test"})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    prefix = f"/api/projects/{ids['project']}/geo-v1"
    decision_map = client.get(f"{prefix}/decision-map", headers=headers)
    decision_map.raise_for_status()
    map_data = decision_map.json()
    _require(map_data["metrics"][0]["value"] == 1, "Organic samples must exclude branded and Mock observations", map_data["metrics"])
    question_map = {item["id"]: item for item in map_data["questions"]}
    _require(question_map[ids["organic_question"]]["visibility_eligible"] is True, "Organic question should be eligible")
    _require(question_map[ids["brand_question"]]["visibility_eligible"] is False, "Brand question must not count for visibility")
    observations = client.get(f"{prefix}/observations", headers=headers)
    observations.raise_for_status()
    observation_map = {item["id"]: item for item in observations.json()}
    _require(observation_map[ids["browser_result"]]["collection_method"] == "web_ui_observation", "Browser method label missing")
    _require(observation_map[ids["mock_result"]]["is_real_evidence"] is False, "Mock must never be promoted to real evidence")
    _require(observation_map[ids["browser_result"]]["brand_status"] == "cited", "Owned citation should surface as cited")
    _require(observation_map[ids["failed_result"]]["brand_status"] == "failed", "Failed result state missing")
    review = client.put(f"{prefix}/observations/{ids['branded_result']}/review", headers=headers, json={"company_mentioned": True, "company_shortlisted": True, "company_recommended": False, "claim_accuracy": "accurate", "citation_valid": False, "note": "人工确认品牌事实"})
    review.raise_for_status()
    _require(review.json()["brand_status"] == "shortlisted", "Manual shortlist review was not applied", review.json())
    claim = client.post(f"{prefix}/brand-claims", headers=headers, json={"title": "私有化部署", "claim_text": "支持按项目范围部署", "category": "capability", "source_url": "https://example.test/capability"})
    claim.raise_for_status()
    action = client.post(f"{prefix}/actions", headers=headers, json={"target_question_id": ids["organic_question"], "source_result_ids": [ids["browser_result"]], "title": "补齐选择指南 FAQ", "category": "content", "priority": "high", "rationale": "证据中出现候选但缺少结构化解释", "hypothesis": "补齐 FAQ 可提高自然推荐机会"})
    action.raise_for_status()
    action_id = action.json()["id"]
    invalid_close = client.patch(f"{prefix}/actions/{action_id}", headers=headers, json={"status": "verified"})
    _require(invalid_close.status_code == 400, "Action must require re-observation before verification", invalid_close.text)
    valid_close = client.patch(f"{prefix}/actions/{action_id}", headers=headers, json={"status": "verified", "verification_result_id": ids["browser_result"], "verification_summary": "复测后仍有官网引用，进入下一轮持续观察。", "concluded_at": datetime.now(UTC).isoformat()})
    valid_close.raise_for_status()
    cross_project = client.post(f"{prefix}/actions", headers=headers, json={"source_result_ids": [ids["other_result"]], "title": "错误关联", "rationale": "不应跨项目关联"})
    _require(cross_project.status_code == 404, "Cross-project evidence link must be rejected", cross_project.text)
    return {"ok": True, "verification_method": "isolated SQLite plus FastAPI TestClient", "project_id": ids["project"], "decision_map_metrics": map_data["metrics"], "observation_count": len(observation_map), "brand_claim_id": claim.json()["id"], "verified_action_id": action_id, "cross_project_rejected": True}


def main() -> None:
    if os.environ.get("GEO_V1_ISOLATED") != "1":
        with tempfile.TemporaryDirectory(prefix="geo-v1-contract-") as temp_dir:
            env = {**os.environ, "DATABASE_URL": f"sqlite:///{Path(temp_dir) / 'geo-v1.sqlite3'}", "AUTO_CREATE_TABLES": "false", "GEO_V1_ISOLATED": "1"}
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env, check=False)
            raise SystemExit(completed.returncode)
    result = _run()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
