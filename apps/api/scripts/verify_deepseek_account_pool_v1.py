"""Isolated contract check for the credential-free DeepSeek browser account pool."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(directory) / 'account-pool.db'}"
        os.environ["AUTO_CREATE_TABLES"] = "false"
        from fastapi.testclient import TestClient

        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.db.session import Base, SessionLocal, engine
        from app.main import create_app
        from app.models import Company, GeoBrowserAccount, User
        from app.services.auth import hash_password, issue_access_token

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        company_a = Company(name="春秋元泉", industry="GEO")
        company_b = Company(name="隔离企业", industry="测试")
        db.add_all([company_a, company_b])
        db.flush()
        user_a = User(name="A", email="pool-a@test.local", password_hash=hash_password("test"), role="company_admin", status="active", company_id=company_a.id)
        user_b = User(name="B", email="pool-b@test.local", password_hash=hash_password("test"), role="company_admin", status="active", company_id=company_b.id)
        db.add_all([user_a, user_b])
        db.flush()
        token_a = issue_access_token(db, user_a)
        token_b = issue_access_token(db, user_b)
        db.commit()
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        client = TestClient(create_app())

        workspace = client.post("/api/v1/workspaces", headers=headers_a, json={"company_id": company_a.id, "slug": "pool-spring-yuan", "brand_name": "春秋元泉"}).json()
        workspace_other = client.post("/api/v1/workspaces", headers=headers_b, json={"company_id": company_b.id, "slug": "pool-other", "brand_name": "隔离企业"}).json()
        workspace_id = workspace["id"]
        question = client.post(f"/api/v1/workspaces/{workspace_id}/question-plans", headers=headers_a, json={"question_text": "企业级大模型治理平台怎么选？", "importance": 5}).json()
        client.post(f"/api/v1/workspaces/{workspace_id}/question-plans", headers=headers_a, json={"question_text": "AI 安全治理产品应该关注哪些能力？", "importance": 4})
        client.post(f"/api/v1/workspaces/{workspace_id}/question-plans", headers=headers_a, json={"question_text": "国内大模型安全平台有哪些选择？", "importance": 4})
        run = client.post(f"/api/v1/workspaces/{workspace_id}/observations/standard", headers=headers_a, json={"repeat_count": 3}).json()["run"]

        account_1 = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a, json={"alias": "deepseek-a01", "ego_task_space_id": 101, "browser_profile_alias": "deepseek-clean"}).json()
        account_2 = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a, json={"alias": "deepseek-a02", "ego_task_space_id": 102, "browser_profile_alias": "deepseek-real"}).json()
        assert account_1["status"] == "onboarding"
        assert client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a, json={"alias": "deepseek-a01", "ego_task_space_id": 103}).status_code == 409
        assert client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a, json={"alias": "deepseek-a03", "ego_task_space_id": 101}).status_code == 409
        fingerprints = {account_1["id"]: "1" * 64, account_2["id"]: "2" * 64}
        for account in (account_1, account_2):
            ready = client.patch(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account['id']}", headers=headers_a, json={"status": "ready", "health_note": "登录验证通过", "session_fingerprint": fingerprints[account["id"]]})
            assert ready.status_code == 200, ready.text
            assert ready.json()["isolation_verified"] is True
        duplicate_profile = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a, json={"alias": "deepseek-a04", "browser_profile_alias": "deepseek-clean"})
        assert duplicate_profile.status_code == 409
        duplicate_fingerprint = client.patch(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_2['id']}", headers=headers_a, json={"status": "ready", "session_fingerprint": "1" * 64})
        assert duplicate_fingerprint.status_code == 409

        lease_1 = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "worker-1", "run_id": run["id"]}).json()
        lease_2 = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "worker-2", "run_id": run["id"]}).json()
        assert lease_1["account"]["id"] == account_1["id"]
        assert lease_2["account"]["id"] == account_2["id"]
        assert lease_1["lease_token"] != lease_2["lease_token"]
        assert client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "worker-3"}).status_code == 409
        assert client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_1['id']}/release", headers=headers_a, json={"lease_token": "wrong-token-that-is-long-enough", "outcome": "success"}).status_code == 409

        cooled = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_1['id']}/release", headers=headers_a, json={"lease_token": lease_1["lease_token"], "outcome": "rate_limited", "cooldown_seconds": 60}).json()
        assert cooled["status"] == "cooldown" and cooled["cooldown_until"]
        released = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_2['id']}/release", headers=headers_a, json={"lease_token": lease_2["lease_token"], "outcome": "success"}).json()
        assert released["status"] == "ready"
        lease_3 = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "worker-3", "run_id": run["id"]}).json()
        assert lease_3["account"]["id"] == account_2["id"]
        reauth = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_2['id']}/release", headers=headers_a, json={"lease_token": lease_3["lease_token"], "outcome": "auth_expired"}).json()
        assert reauth["status"] == "reauth_required"

        assert client.patch(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_1['id']}", headers=headers_a, json={"status": "ready", "health_note": "冷却人工解除", "session_fingerprint": "1" * 64}).status_code == 200
        import_lease = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "yao-deepseek-worker", "run_id": run["id"]}).json()
        dataset = {
            "schema_version": "yao-deepseek-crawler/v1",
            "run": {"id": "account-pool-live-1", "transport": "web_ui"},
            "samples": [{
                "sample_id": "account-pool-q1-r1",
                "question": question["question_text"],
                "repeat_index": 1,
                "ok": True,
                "raw_path": "raw/q1-r1.json",
                "finished_at": "2026-08-01T08:00:00Z",
                "result": {
                    "answer": {"text": "回答未提及春秋元泉。"},
                    "references": {"items": [{"number": 1, "source": "公开资料", "url": "https://example.test/source"}]},
                    "artifacts": {"screenshots": ["screenshots/q1-r1.png"]},
                    "transport": "web_ui",
                    "options": {"search": True},
                },
            }],
        }
        bad_import = client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/yao/deepseek-stage1",
            headers=headers_a,
            json={"target_run_id": run["id"], "browser_account_id": account_2["id"], "lease_token": import_lease["lease_token"], "artifact_base_uri": "file:///private/pool-run", "dataset": dataset},
        )
        assert bad_import.status_code == 409
        imported = client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/yao/deepseek-stage1",
            headers=headers_a,
            json={"target_run_id": run["id"], "browser_account_id": import_lease["account"]["id"], "lease_token": import_lease["lease_token"], "artifact_base_uri": "file:///private/pool-run", "dataset": dataset},
        )
        assert imported.status_code == 201, imported.text
        evidence = client.get(f"/api/v1/workspaces/{workspace_id}/evidence", headers=headers_a).json()[0]
        assert evidence["sampling_environment"]["browser_account_id"] == import_lease["account"]["id"]
        assert evidence["sampling_environment"]["browser_account_alias"] == "deepseek-a01"
        assert evidence["sampling_environment"]["browser_account_cohort"] == "clean_baseline"
        after_import = {row["id"]: row for row in client.get(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a).json()}
        assert after_import[account_1["id"]]["status"] == "ready"
        assert after_import[account_1["id"]]["lease_worker_id"] is None

        client.patch(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_2['id']}", headers=headers_a, json={"status": "ready", "health_note": "重新登录完成", "session_fingerprint": "2" * 64})
        batch_response = client.post(f"/api/v1/workspaces/{workspace_id}/sampling-batches", headers=headers_a, json={})
        assert batch_response.status_code == 202, batch_response.text
        batch = batch_response.json()
        assert batch["total_samples"] == 18 and len(batch["samples"]) == 18
        matrix = {(row["browser_account_id"], row["question_plan_id"], row["repeat_index"]) for row in batch["samples"]}
        assert len(matrix) == 18
        assert len({row["browser_account_id"] for row in batch["samples"]}) == 2
        assert len({row["question_plan_id"] for row in batch["samples"]}) == 3
        assert {row["repeat_index"] for row in batch["samples"]} == {1, 2, 3}
        assert client.post(f"/api/v1/workspaces/{workspace_id}/sampling-batches", headers=headers_a, json={}).status_code == 409
        claimed = client.post(f"/api/v1/workspaces/{workspace_id}/sampling-worker/claim", headers=headers_a, json={"worker_id": "profile-worker"}).json()
        completed = client.post(
            f"/api/v1/workspaces/{workspace_id}/sampling-worker/samples/{claimed['sample_id']}/complete",
            headers=headers_a,
            json={
                "lease_token": claimed["lease_token"],
                "answer_text": "春秋元泉提供企业级 AI 安全治理能力。",
                "references": [{"number": 1, "title": "春秋元泉官网", "url": "https://icqtoken.ichunqiu.com/"}],
                "brand_status": "cited",
                "brand_position": 1,
                "conversation_url": "https://chat.deepseek.com/a/chat/s/test-sample",
                "raw_artifact_uri": "file:///private/profile-worker/raw/sample.json",
                "screenshot_uri": "file:///private/profile-worker/screenshots/sample.png",
                "captured_at": "2026-08-01T09:00:00Z",
                "conversation_deleted_at": "2026-08-01T09:00:05Z",
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["completed_samples"] == 1
        latest_batch = client.get(f"/api/v1/workspaces/{workspace_id}/sampling-batches/latest", headers=headers_a).json()
        assert latest_batch["id"] == batch["id"] and latest_batch["samples"][0]["evidence_id"]

        client.patch(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_1['id']}", headers=headers_a, json={"status": "disabled", "health_note": "过期租约测试时停用"})
        client.patch(f"/api/v1/workspaces/{workspace_id}/browser-accounts/{account_2['id']}", headers=headers_a, json={"status": "ready", "health_note": "重新登录完成", "session_fingerprint": "2" * 64})
        expiring = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "stale-worker", "lease_seconds": 60}).json()
        stale = db.get(GeoBrowserAccount, expiring["account"]["id"])
        stale.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        recovered = client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts/lease", headers=headers_a, json={"worker_id": "recovery-worker"})
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["account"]["id"] == account_2["id"]

        rows = client.get(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_a).json()
        serialized = json.dumps(rows).lower()
        for forbidden in ("password", "cookie", "local_storage", "lease_token_hash", "phone"):
            assert forbidden not in serialized
        assert client.get(f"/api/v1/workspaces/{workspace_id}/browser-accounts", headers=headers_b).status_code == 404
        assert client.get(f"/api/v1/workspaces/{workspace_other['id']}/browser-accounts", headers=headers_a).status_code == 404
        assert client.post(f"/api/v1/workspaces/{workspace_id}/browser-accounts", json={"alias": "no-auth", "ego_task_space_id": 999}).status_code == 401

        persisted = db.get(GeoBrowserAccount, recovered.json()["account"]["id"])
        assert persisted.lease_token_hash == _hash_for_test(recovered.json()["lease_token"])
        assert persisted.lease_token_hash != recovered.json()["lease_token"]
        print(json.dumps({"ok": True, "accounts": 2, "rotation": [account_1["id"], account_2["id"]], "evidence_id": evidence["id"], "batch_samples": 18, "cross_workspace_rejected": True}, ensure_ascii=False))


def _hash_for_test(value: str) -> str:
    from hashlib import sha256

    return sha256(value.encode()).hexdigest()


if __name__ == "__main__":
    main()
