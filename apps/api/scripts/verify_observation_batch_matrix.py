"""Verify the 5 providers x 10 questions x 100 repeats orchestration contract."""

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
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(directory) / 'batch-contract.db'}"
        os.environ["AUTO_CREATE_TABLES"] = "false"

        from fastapi.testclient import TestClient
        from sqlalchemy import select

        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.db.session import Base, SessionLocal, engine
        from app.main import create_app
        from app.models import Company, LLMProvider, LLMProviderTestRun, QueueJob, User
        from app.services.auth import hash_password, issue_access_token
        from app.v1 import routes

        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            company = Company(name="春秋元泉", industry="网络安全", brand_aliases=[])
            db.add(company)
            db.flush()
            user = User(
                name="Batch verifier",
                email="batch-verifier@local.test",
                password_hash=hash_password("test"),
                role="company_admin",
                status="active",
                company_id=company.id,
            )
            db.add(user)
            providers = [
                LLMProvider(name="DeepSeek", provider_type="deepseek_web_search", model_name="deepseek", api_base_url="https://example.test", auth_config={"api_key": "test"}, cost_rule={"platform_key": "deepseek"}, status="active"),
                LLMProvider(name="豆包", provider_type="volcengine_ark", model_name="doubao", api_base_url="https://example.test", auth_config={"api_key": "test"}, cost_rule={"platform_key": "doubao"}, status="active"),
                LLMProvider(name="千问", provider_type="bailian_qwen_responses", model_name="qwen", api_base_url="https://example.test", auth_config={"api_key": "test"}, cost_rule={"platform_key": "qwen"}, status="active"),
                LLMProvider(name="GLM", provider_type="volcengine_ark", model_name="glm", api_base_url="https://example.test", auth_config={"api_key": "test"}, cost_rule={"platform_key": "glm"}, status="active"),
                LLMProvider(name="Kimi", provider_type="kimi_web_search", model_name="kimi", api_base_url="https://example.test", auth_config={"api_key": "test"}, cost_rule={"platform_key": "kimi"}, status="active"),
            ]
            db.add_all(providers)
            db.flush()
            db.add_all([
                LLMProviderTestRun(provider_id=provider.id, actor_user_id=user.id, ok=True, prompt_text="联网验证")
                for provider in providers
            ])
            access_token = issue_access_token(db, user)
            db.commit()
            provider_ids = [provider.id for provider in providers]
            company_id = company.id

        projected_calls_by_provider = []
        routes.diagnose_provider = lambda _provider: {"ready": True, "supports_web_search": True}
        routes.workspace_worker_is_online = lambda _db, _workspace_id: True
        routes.enforce_monthly_search_budget = lambda _db, provider, projected_calls: projected_calls_by_provider.append((provider.id, projected_calls))
        client = TestClient(create_app())
        headers = {"Authorization": f"Bearer {access_token}"}
        workspace = client.post("/api/v1/workspaces", headers=headers, json={
            "company_id": company_id,
            "slug": "batch-contract",
            "brand_name": "春秋元泉",
            "brand_aliases": [],
        }).json()
        empty_history = client.get(
            f"/api/v1/workspaces/{workspace['id']}/observation-batches?page=1&page_size=20",
            headers=headers,
        )
        empty_history.raise_for_status()
        assert empty_history.json()["items"] == []
        assert empty_history.json()["pagination"]["total"] == 0
        question_ids = []
        for index in range(1, 11):
            question = client.post(f"/api/v1/workspaces/{workspace['id']}/question-plans", headers=headers, json={
                "question_text": f"批量观测采购问题 {index} 怎么选？",
                "importance": 5,
            })
            question.raise_for_status()
            question_ids.append(question.json()["id"])

        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/observation-batches",
            headers=headers,
            json={"provider_ids": provider_ids, "question_plan_ids": question_ids, "repeat_count": 100},
        )
        response.raise_for_status()
        batch = response.json()
        assert batch["total"] == 5000
        assert batch["pending"] == 5000
        assert len(batch["provider_groups"]) == 5
        assert len(batch["question_groups"]) == 10
        assert all(group["total"] == 1000 for group in batch["provider_groups"])
        assert all(group["total"] == 500 for group in batch["question_groups"])
        assert projected_calls_by_provider == [(provider_id, 1000) for provider_id in provider_ids]

        history = client.get(
            f"/api/v1/workspaces/{workspace['id']}/observation-batches?page=1&page_size=1",
            headers=headers,
        )
        history.raise_for_status()
        assert history.json()["pagination"] == {"page": 1, "page_size": 1, "total": 1, "total_pages": 1}
        assert history.json()["items"][0]["batch_id"] == batch["batch_id"]

        detail_page = client.get(
            f"/api/v1/workspaces/{workspace['id']}/observation-batches/{batch['batch_id']}?task_page=2&task_page_size=7",
            headers=headers,
        )
        detail_page.raise_for_status()
        assert detail_page.json()["task_pagination"] == {"page": 2, "page_size": 7, "total": 5000, "total_pages": 715}
        assert len(detail_page.json()["tasks"]) == 7

        with SessionLocal() as db:
            children = list(db.scalars(select(QueueJob).where(
                QueueJob.job_type == "geo_observation.collect",
            ).order_by(QueueJob.id)))
            child_count = len(children)
            assert child_count == 5000
            # The first scheduling wave must cover every selected platform,
            # rather than queueing all repeats for the first provider first.
            assert [int(job.payload_json["provider_id"]) for job in children[:5]] == provider_ids
            from app.models import GeoObservationTask
            tasks = list(db.scalars(select(GeoObservationTask).order_by(GeoObservationTask.id).limit(3)))
            tasks[0].status = "completed"
            tasks[1].status = "failed"
            tasks[1].error_detail = "联网渠道超时"
            tasks[2].status = "running"
            db.add_all(tasks)
            db.commit()

        mixed = client.get(
            f"/api/v1/workspaces/{workspace['id']}/observation-batches/{batch['batch_id']}",
            headers=headers,
        )
        mixed.raise_for_status()
        assert mixed.json()["status"] == "running"
        assert mixed.json()["succeeded"] == 1
        assert mixed.json()["failed"] == 1
        assert mixed.json()["running"] == 1
        assert mixed.json()["errors"] == ["联网渠道超时"]

        edited = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/question-plans/{question_ids[0]}",
            headers=headers,
            json={"question_text": "编辑后的常用采购问题怎么选？"},
        )
        edited.raise_for_status()
        assert edited.json()["question_text"] == "编辑后的常用采购问题怎么选？"

        print(json.dumps({
            "ok": True,
            "batch_id": batch["batch_id"],
            "matrix": "5x10x100",
            "total": batch["total"],
            "provider_groups": len(batch["provider_groups"]),
            "question_groups": len(batch["question_groups"]),
            "empty_history": True,
            "single_batch_history": history.json()["pagination"],
            "detail_task_pagination": detail_page.json()["task_pagination"],
            "mixed_status_counts": {
                key: mixed.json()[key] for key in ("pending", "running", "succeeded", "failed")
            },
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
