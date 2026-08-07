"""Isolated API/worker contract verification for the local Codex Agent P0."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


class FakeCodexRuntime:
    def run_structured(self, **kwargs):
        from app.services.codex_agent_runtime import CodexTurnResult

        kwargs["on_started"]("test-thread", "test-turn")
        kwargs["on_event"](
            "item/completed",
            {"item": {"type": "webSearch", "query": "知乎官方内容规范"}},
        )
        payload = {
            "platform_research": [
                {
                    "platform_key": "zhihu",
                    "tone": "先结论后论证，避免硬广",
                    "restrictions": ["不伪造经历", "不使用绝对化承诺"],
                    "source_urls": ["https://www.zhihu.com/term/zhihu-terms"],
                },
                {
                    "platform_key": "wechat",
                    "tone": "移动端短段落和清晰小标题",
                    "restrictions": ["不诱导分享"],
                    "source_urls": ["https://weixin.qq.com/cgi-bin/readtemplate?t=weixin_external_links_content_management_specification"],
                },
            ],
            "brand_research": {
                "verified_facts": [
                    {
                        "statement": "春秋元泉官网展示 GEO 工作台",
                        "source_url": "https://icqtoken.ichunqiu.com/",
                    }
                ],
                "unknowns": ["未提供可公开核验的客户案例"],
            },
            "master": {
                "title": "企业如何评估 Token 统一管控平台",
                "summary": "从凭据、费用、权限与审计四个可核验维度评估。",
                "body_markdown": "## 先给结论\n\n选型应先验证凭据隔离、成本归因、权限与审计。",
                "claims": [
                    {
                        "text": "春秋元泉官网展示 GEO 工作台",
                        "source_url": "https://icqtoken.ichunqiu.com/",
                        "verification_status": "source_linked",
                    },
                    {
                        "text": "存在某大型客户成功案例",
                        "source_url": None,
                        "verification_status": "pending",
                    },
                ],
            },
            "variants": [
                {
                    "platform_key": "zhihu",
                    "title": "Token 统一管控平台怎么选？先看四个可验证指标",
                    "summary": "不看宣传口号，看可实测的管控能力。",
                    "body_markdown": "## 结论\n\n先用四个问题筛选，再做小范围验证。",
                    "tags": ["Token 管理", "企业 AI"],
                    "adaptation_notes": ["问答式开头", "保留反例和边界"],
                },
                {
                    "platform_key": "wechat",
                    "title": "企业 Token 管控选型：别略过这 4 项验证",
                    "summary": "一份适合项目启动会的短清单。",
                    "body_markdown": "## 为什么先验证\n\n每项能力都要能用现场记录回答。",
                    "tags": ["企业 AI", "成本治理"],
                    "adaptation_notes": ["移动端短段落", "标题强调可执行清单"],
                },
            ],
        }
        return CodexTurnResult(
            thread_id="test-thread",
            turn_id="test-turn",
            final_response=json.dumps(payload, ensure_ascii=False),
            usage={"total": {"totalTokens": 123}},
            runtime_events=[],
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(directory) / 'agent.db'}"
        os.environ["AUTO_CREATE_TABLES"] = "false"
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select

        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.db.session import Base, SessionLocal, engine
        from app.main import create_app
        from app.models import Company, User
        from app.models.cleanroom_v1 import (
            GeoAgentArtifact,
            GeoAgentEvent,
            GeoAgentRun,
            GeoContentAsset,
            GeoContentClaim,
            GeoDistributionRun,
            GeoOptimizationAction,
            GeoPlatformVariant,
            GeoWorkspace,
        )
        from app.services.auth import create_access_token, hash_password
        from app.v1 import routes
        from app.v1.agent_orchestration import execute_agent_run

        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            company = Company(name="春秋元泉", industry="GEO")
            other_company = Company(name="隔离企业", industry="test")
            db.add_all([company, other_company])
            db.flush()
            user = User(
                name="Agent tester",
                email="agent@example.test",
                password_hash=hash_password("test"),
                role="company_admin",
                status="active",
                company_id=company.id,
            )
            other_user = User(
                name="Other",
                email="other@example.test",
                password_hash=hash_password("test"),
                role="company_admin",
                status="active",
                company_id=other_company.id,
            )
            db.add_all([user, other_user])
            db.flush()
            workspace = GeoWorkspace(
                company_id=company.id,
                slug="spring-yuan-agent",
                brand_name="春秋元泉",
                brand_aliases=["春秋元泉 GEO"],
                website_url="https://icqtoken.ichunqiu.com/",
            )
            other_workspace = GeoWorkspace(
                company_id=other_company.id,
                slug="other-agent",
                brand_name="隔离企业",
            )
            db.add_all([workspace, other_workspace])
            db.flush()
            action = GeoOptimizationAction(
                workspace_id=workspace.id,
                title="补齐 Token 统一管控选型内容",
                rationale="真实观测中缺少品牌答案",
                priority="high",
            )
            action_two = GeoOptimizationAction(
                workspace_id=workspace.id,
                title="第二个 Agent 任务",
                rationale="验证中止状态",
                priority="medium",
            )
            db.add_all([action, action_two])
            db.commit()
            ids = {
                "workspace": workspace.id,
                "other_workspace": other_workspace.id,
                "action": action.id,
                "action_two": action_two.id,
                "user": user.id,
                "other_user": other_user.id,
            }

        routes.diagnose_local_codex = lambda: {
            "runtime_key": "local_codex",
            "sdk_installed": True,
            "sdk_version": "test",
            "runtime_version": "test",
            "ready": True,
            "login_status": "chatgpt_authenticated",
            "default_model": "gpt-test",
            "available_models": ["gpt-test"],
            "error": None,
        }
        client = TestClient(create_app())
        headers = {"Authorization": f"Bearer {create_access_token(ids['user'])}"}
        other_headers = {"Authorization": f"Bearer {create_access_token(ids['other_user'])}"}
        created = client.post(
            f"/api/v1/workspaces/{ids['workspace']}/actions/{ids['action']}/agent-runs",
            headers=headers,
            json={"selected_platforms": ["zhihu", "wechat"]},
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["id"]
        duplicate = client.post(
            f"/api/v1/workspaces/{ids['workspace']}/actions/{ids['action']}/agent-runs",
            headers=headers,
            json={},
        )
        assert duplicate.status_code == 409, duplicate.text
        assert client.get(
            f"/api/v1/workspaces/{ids['workspace']}/agent-runs/{run_id}",
            headers=other_headers,
        ).status_code == 404

        with SessionLocal() as db:
            run = db.get(GeoAgentRun, run_id)
            execute_agent_run(db, run, runtime=FakeCodexRuntime())
            db.refresh(run)
            assert run.status == "awaiting_review"
            assert run.stage == "awaiting_review"
            assert db.scalar(select(func.count()).select_from(GeoAgentEvent).where(GeoAgentEvent.agent_run_id == run.id)) >= 6
            assert db.scalar(select(func.count()).select_from(GeoAgentArtifact).where(GeoAgentArtifact.agent_run_id == run.id)) == 1
            asset = db.scalar(select(GeoContentAsset).where(GeoContentAsset.id == run.result_snapshot["asset_id"]))
            assert asset and asset.status == "draft"
            assert db.scalar(select(func.count()).select_from(GeoPlatformVariant).where(GeoPlatformVariant.content_asset_id == asset.id)) == 2
            assert db.scalar(select(func.count()).select_from(GeoContentClaim).where(GeoContentClaim.content_asset_id == asset.id)) == 2
            assert db.scalar(select(func.count()).select_from(GeoDistributionRun)) == 0

        second = client.post(
            f"/api/v1/workspaces/{ids['workspace']}/actions/{ids['action_two']}/agent-runs",
            headers=headers,
            json={"selected_platforms": ["zhihu"]},
        )
        assert second.status_code == 202, second.text
        second_id = second.json()["id"]
        interrupted = client.post(
            f"/api/v1/workspaces/{ids['workspace']}/agent-runs/{second_id}/interrupt",
            headers=headers,
        )
        assert interrupted.status_code == 200, interrupted.text
        assert interrupted.json()["status"] == "cancelling"
        with SessionLocal() as db:
            row = db.get(GeoAgentRun, second_id)
            row.status = "cancelled"
            row.codex_thread_id = "resume-thread"
            db.commit()
        resumed = client.post(
            f"/api/v1/workspaces/{ids['workspace']}/agent-runs/{second_id}/resume",
            headers=headers,
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["status"] == "resuming"
        events = client.get(
            f"/api/v1/workspaces/{ids['workspace']}/agent-runs/{run_id}/events",
            headers=headers,
        )
        assert events.status_code == 200 and events.json()[-1]["stage"] == "awaiting_review"
        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run_id,
                    "platform_variants": 2,
                    "distribution_runs": 0,
                    "workspace_isolation": True,
                    "interrupt_resume": True,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
