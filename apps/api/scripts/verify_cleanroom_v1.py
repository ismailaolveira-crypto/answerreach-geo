"""Isolated contract check for the clean-room Spring Yuan GEO V1 API."""

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
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(directory) / 'cleanroom.db'}"
        os.environ["AUTO_CREATE_TABLES"] = "false"
        from fastapi.testclient import TestClient

        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.db.session import Base, SessionLocal, engine
        from app.main import create_app
        from app.models import Company, User
        from app.services.auth import create_access_token, hash_password

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        company_a = Company(name="春秋元泉", industry="GEO")
        company_b = Company(name="隔离企业", industry="测试")
        db.add_all([company_a, company_b])
        db.flush()
        user_a = User(name="A", email="a@cleanroom.local", password_hash=hash_password("test"), role="company_admin", status="active", company_id=company_a.id)
        user_b = User(name="B", email="b@cleanroom.local", password_hash=hash_password("test"), role="company_admin", status="active", company_id=company_b.id)
        db.add_all([user_a, user_b])
        db.commit()
        headers_a = {"Authorization": f"Bearer {create_access_token(user_a.id)}"}
        headers_b = {"Authorization": f"Bearer {create_access_token(user_b.id)}"}
        client = TestClient(create_app())

        workspace_a = client.post("/api/v1/workspaces", headers=headers_a, json={"company_id": company_a.id, "slug": "spring-yuan", "brand_name": "春秋元泉", "brand_aliases": ["春秋元泉 GEO"]}).json()
        workspace_b = client.post("/api/v1/workspaces", headers=headers_b, json={"company_id": company_b.id, "slug": "isolated-brand", "brand_name": "隔离企业"}).json()
        workspace_id = workspace_a["id"]
        question = client.post(f"/api/v1/workspaces/{workspace_id}/question-plans", headers=headers_a, json={"question_text": "企业 GEO 优化服务应该如何选择？", "importance": 5}).json()
        standard_run = client.post(f"/api/v1/workspaces/{workspace_id}/observations/standard", headers=headers_a, json={"repeat_count": 3})
        assert standard_run.status_code == 202, standard_run.text
        assert standard_run.json()["run"]["status"] == "queued"
        assert standard_run.json()["question_count"] == 1
        assert [item["key"] for item in standard_run.json()["providers"]] == ["deepseek", "doubao", "qianwen", "yuanbao"]
        empty_map = client.get(f"/api/v1/workspaces/{workspace_id}/decision-map", headers=headers_a).json()
        assert len(empty_map["models"]) == 4
        assert all(cell["evidence"] is None for cell in empty_map["cells"])
        planned_native = client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/yao/deepseek-stage1",
            headers=headers_a,
            json={
                "target_run_id": standard_run.json()["run"]["id"],
                "artifact_base_uri": "file:///private/live-run",
                "dataset": {
                    "schema_version": "yao-deepseek-crawler/v1",
                    "run": {"id": "live-run", "transport": "web_ui"},
                    "samples": [{
                        "sample_id": "live-q1-r1", "question": question["question_text"], "repeat_index": 1, "ok": True,
                        "raw_path": "raw/q1-r1.json", "finished_at": "2026-07-31T12:00:00Z",
                        "result": {
                            "answer": {"text": "真实网页端采样：答案中未提及春秋元泉。"},
                            "references": {"items": [{"number": 1, "source": "示例来源", "url": "https://example.test/source"}]},
                            "artifacts": {"screenshots": ["screenshots/q1-r1.png"]},
                            "transport": "web_ui", "options": {"search": True},
                        },
                    }],
                },
            },
        )
        assert planned_native.status_code == 201, planned_native.text
        assert planned_native.json()["run_id"] == standard_run.json()["run"]["id"]
        assert client.get(f"/api/v1/workspaces/{workspace_id}/decision-map", headers=headers_a).json()["cells"][0]["evidence"]["run_id"] == standard_run.json()["run"]["id"]
        imported = client.post(f"/api/v1/workspaces/{workspace_id}/imports/yao", headers=headers_a, json={
            "platform": "deepseek", "sample_mode": "browser_assisted", "evidence_level": "auditable", "samples": [{
                "sample_id": "deepseek-q1-r1", "question": question["question_text"], "repeat_index": 1, "ok": True,
                "raw_artifact_uri": "file:///evidence/deepseek-q1-r1.json", "screenshot_uri": "file:///evidence/deepseek-q1-r1.png",
                "sampling_environment": {"device": "desktop", "region": "CN", "fresh_session": True},
                "answer_text": "春秋元泉 GEO 提供可验证的企业 AI 答案观测和证据闭环。", "brand_status": "cited", "brand_position": 1,
                "references": [{"number": 1, "source": "春秋元泉官网", "domain": "ichunqiu.com", "title": "春秋元泉 GEO", "url": "https://example.test/source"}],
            }],
        })
        assert imported.status_code == 201, imported.text
        score = imported.json()
        assert score["metrics"]["eligible_samples"] == 1
        yao_fixture = API_ROOT.parents[2] / "research" / "yao-geo-skills" / "skills" / "yao-deepseek-crawler" / "fixtures" / "sample-deepseek-crawl.json"
        native_import = client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/yao/deepseek-stage1",
            headers=headers_a,
            json={"dataset": json.loads(yao_fixture.read_text()), "artifact_base_uri": "file:///private/yao-run"},
        )
        assert native_import.status_code == 201, native_import.text
        assert native_import.json()["metrics"]["eligible_samples"] == 3
        doubao_fixture = API_ROOT.parents[2] / "research" / "yao-geo-skills" / "skills" / "yao-doubao-crawler" / "fixtures" / "sample-doubao-mobile-crawl.json"
        doubao_import = client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/yao/doubao-stage1",
            headers=headers_a,
            json={"dataset": json.loads(doubao_fixture.read_text()), "artifact_base_uri": "file:///private/doubao-run"},
        )
        assert doubao_import.status_code == 201, doubao_import.text
        assert doubao_import.json()["metrics"]["eligible_samples"] == 1
        decision_map = client.get(f"/api/v1/workspaces/{workspace_id}/decision-map", headers=headers_a)
        assert decision_map.status_code == 200, decision_map.text
        assert decision_map.json()["cells"][0]["evidence"]["model_label"] == "DeepSeek"
        evidence_rows = client.get(f"/api/v1/workspaces/{workspace_id}/evidence", headers=headers_a).json()
        evidence = evidence_rows[0]
        assert evidence["is_real_provider_evidence"] is True
        doubao_evidence = next(row for row in evidence_rows if row["model_key"] == "doubao")
        assert doubao_evidence["screenshot_uri"].endswith("screenshots/q01-r01/screen-01.png")
        immutable_attempt = client.patch(f"/api/v1/workspaces/{workspace_id}/evidence/{evidence['id']}", headers=headers_a, json={})
        assert immutable_attempt.status_code >= 400
        action = client.post(f"/api/v1/workspaces/{workspace_id}/actions", headers=headers_a, json={"title": "补齐 FAQ", "rationale": "补齐可引用的采购选择证据", "source_evidence_id": evidence["id"]}).json()
        premature = client.patch(f"/api/v1/workspaces/{workspace_id}/actions/{action['id']}", headers=headers_a, json={"status": "closed"})
        assert premature.status_code == 422
        reobserve = client.post(f"/api/v1/workspaces/{workspace_id}/actions/{action['id']}/re-observations", headers=headers_a, json={"run_id": evidence["run_id"], "evidence_id": evidence["id"], "conclusion": "引用状态已被可审计样本确认", "measured_delta": {"citation_rate": 100}})
        assert reobserve.status_code == 201, reobserve.text
        assert client.patch(f"/api/v1/workspaces/{workspace_id}/actions/{action['id']}", headers=headers_a, json={"status": "closed"}).status_code == 200
        audit_payload = {
            "target_url": "https://example.test/geo",
            "title": "春秋元泉 GEO 服务说明",
            "body": "## 能力\n提供可审计的答案证据。\n## 常见问题 FAQ\n包含 3 个可验证数据点。" * 8,
            "source_urls": ["https://example.test/source"],
        }
        first_audit = client.post(f"/api/v1/workspaces/{workspace_id}/content-audits", headers=headers_a, json=audit_payload)
        second_audit = client.post(f"/api/v1/workspaces/{workspace_id}/content-audits", headers=headers_a, json=audit_payload)
        assert first_audit.status_code == 201, first_audit.text
        assert second_audit.status_code == 201, second_audit.text
        assert first_audit.json()["content_fingerprint"] == second_audit.json()["content_fingerprint"]
        assert first_audit.json()["score"] == second_audit.json()["score"]
        assert first_audit.json()["audit_version"] == "heige-deterministic-geo-audit/1.1"
        assert first_audit.json()["checks"]["crawler_access"] == "unavailable"
        assert first_audit.json()["checks"]["ai_discovery_files"] == "unavailable"
        assert client.get(f"/api/v1/workspaces/{workspace_id}/evidence", headers=headers_b).status_code == 404
        cross_action = client.post(f"/api/v1/workspaces/{workspace_b['id']}/actions", headers=headers_b, json={"title": "越权引用", "rationale": "不应允许", "source_evidence_id": evidence["id"]})
        assert cross_action.status_code == 404
        print(json.dumps({"ok": True, "workspace_id": workspace_id, "scorecard": score["id"], "evidence_id": evidence["id"], "closed_action_id": action["id"], "cross_workspace_rejected": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
