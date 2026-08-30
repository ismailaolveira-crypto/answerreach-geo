"""Isolated persistence check for one official DeepSeek search observation."""

import json
import os
import sys
import tempfile
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        os.environ["DATABASE_URL"] = f"sqlite:///{root / 'official-observation.db'}"
        os.environ["AUTO_CREATE_TABLES"] = "false"

        from fastapi.testclient import TestClient

        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.db.session import Base, SessionLocal, engine
        from app.main import create_app
        from app.models import Company, LLMProvider, User
        from app.services.auth import hash_password, issue_access_token
        from app.services.llm_provider import ProviderAnswer
        from app.v1 import routes

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        company = Company(
            name="春秋元泉",
            industry="网络安全",
            website_url="https://icqtoken.ichunqiu.com/",
            brand_aliases=["春秋元泉 GEO"],
        )
        db.add(company)
        db.flush()
        user = User(
            name="Verifier",
            email="official-api@local.test",
            password_hash=hash_password("test"),
            role="company_admin",
            status="active",
            company_id=company.id,
        )
        provider = LLMProvider(
            name="DeepSeek 官方联网 GEO 采集",
            provider_type="deepseek_web_search",
            model_name="deepseek-v4-pro",
            api_base_url="https://api.deepseek.com/anthropic",
            auth_config={"api_key": "test-only"},
            cost_rule={},
            status="active",
        )
        db.add_all([user, provider])
        db.flush()
        access_token = issue_access_token(db, user)
        db.commit()

        class FakeAdapter:
            def answer(self, prompt_text, _company, _project, _competitors):
                return ProviderAnswer(
                    prompt_text=prompt_text,
                    raw_answer="采购时可比较统一管控、私有化和审计能力；春秋元泉可作为候选之一。",
                    answer_summary="采购时可比较统一管控、私有化和审计能力。",
                    source_items=[{
                        "number": 1,
                        "title": "春秋元泉官网",
                        "url": "https://icqtoken.ichunqiu.com/",
                        "domain": "icqtoken.ichunqiu.com",
                    }],
                    raw_provider_payload={"id": "msg_test", "content": [{"type": "text", "text": "answer"}]},
                    collection_method="official_api_web_search",
                    search_verified=True,
                    search_event_count=2,
                    search_verification={
                        "gate": "server_tool_use:web_search + web_search_tool_result + sources",
                        "web_search_call_count": 1,
                        "web_search_result_block_count": 1,
                        "source_count": 1,
                    },
                )

        routes.get_search_provider = lambda _provider: FakeAdapter()
        routes.OFFICIAL_API_ARTIFACT_ROOT = root / "artifacts"
        client = TestClient(create_app())
        headers = {"Authorization": f"Bearer {access_token}"}
        workspace = client.post(
            "/api/v1/workspaces",
            headers=headers,
            json={
                "company_id": company.id,
                "slug": "spring-yuan-official",
                "brand_name": "春秋元泉",
                "brand_aliases": ["春秋元泉 GEO"],
                "website_url": "https://icqtoken.ichunqiu.com/",
            },
        ).json()
        question = client.post(
            f"/api/v1/workspaces/{workspace['id']}/question-plans",
            headers=headers,
            json={"question_text": "企业级大模型治理平台怎么选？", "importance": 5},
        ).json()
        invalid_repeat = client.post(
            f"/api/v1/workspaces/{workspace['id']}/observations/deepseek-official",
            headers=headers,
            json={
                "question_plan_id": question["id"],
                "provider_id": provider.id,
                "repeat_index": 2,
                "repeat_count": 1,
                "observation_group_id": "obs_invalid_group",
            },
        )
        assert invalid_repeat.status_code == 422
        group_id = "obs_contract_group_001"
        results = []
        for repeat_index in range(1, 6):
            response = client.post(
                f"/api/v1/workspaces/{workspace['id']}/observations/deepseek-official",
                headers=headers,
                json={
                    "question_plan_id": question["id"],
                    "provider_id": provider.id,
                    "repeat_index": repeat_index,
                    "repeat_count": 5,
                    "observation_group_id": group_id,
                },
            )
            assert response.status_code == 201, response.text
            results.append(response.json())
        result = results[-1]
        evidence = result["evidence"]
        assert result["run"]["status"] == "completed"
        assert evidence["collection_method"] == "official_api_web_search"
        assert evidence["evidence_level"] == "auditable"
        assert evidence["is_real_provider_evidence"] is True
        assert evidence["brand_status"] == "cited"
        assert len(evidence["source_items"]) == 1
        assert evidence["sampling_environment"]["repeat_index"] == 5
        assert evidence["sampling_environment"]["repeat_count"] == 5
        assert evidence["sampling_environment"]["observation_group_id"] == group_id
        grouped_evidence = client.get(
            f"/api/v1/workspaces/{workspace['id']}/evidence", headers=headers
        ).json()
        grouped_evidence = [
            item for item in grouped_evidence
            if item["sampling_environment"].get("observation_group_id") == group_id
        ]
        assert len(grouped_evidence) == 5
        assert sorted(item["sampling_environment"]["repeat_index"] for item in grouped_evidence) == [1, 2, 3, 4, 5]
        artifact = Path(evidence["raw_artifact_uri"].removeprefix("file://"))
        archived = json.loads(artifact.read_text(encoding="utf-8"))
        assert archived["raw_provider_response"]["id"] == "msg_test"
        decision_map = client.get(
            f"/api/v1/workspaces/{workspace['id']}/decision-map",
            headers=headers,
        ).json()
        deepseek_cell = next(
            cell for cell in decision_map["cells"]
            if cell["question_plan_id"] == question["id"] and cell["model_key"] == "deepseek"
        )
        assert deepseek_cell["evidence"]["id"] == evidence["id"]
        print(json.dumps({
            "ok": True,
            "run_id": result["run"]["id"],
            "evidence_id": evidence["id"],
            "artifact_archived": artifact.exists(),
            "sources": len(evidence["source_items"]),
            "grouped_samples": len(grouped_evidence),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
