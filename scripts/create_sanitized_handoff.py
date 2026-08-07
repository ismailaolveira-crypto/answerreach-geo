#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sqlite3
import string
import tarfile
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ID = 1
TASK_ID = 8
REPORT_ID = 6
PROVIDER_ID = 10
SCHEDULE_ID = 1


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(source: Path, target: Path) -> None:
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def count(conn: sqlite3.Connection, table: str, where: str = "1=1") -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


def sanitize_database(path: Path) -> tuple[dict, str]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    password = "Handoff-" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(18)
    )
    try:
        conn.execute("PRAGMA foreign_keys=OFF")

        project_tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if any(
                column[1] == "project_id"
                for column in conn.execute(f"PRAGMA table_info({row[0]})")
            )
        ]
        for table in project_tables:
            conn.execute(f"DELETE FROM {table} WHERE project_id != ?", (PROJECT_ID,))

        company_id = int(
            conn.execute("SELECT company_id FROM projects WHERE id=?", (PROJECT_ID,)).fetchone()[0]
        )
        conn.execute("DELETE FROM projects WHERE id != ?", (PROJECT_ID,))
        conn.execute("DELETE FROM companies WHERE id != ?", (company_id,))
        conn.execute("DELETE FROM target_questions WHERE project_id != ?", (PROJECT_ID,))
        conn.execute("DELETE FROM keywords WHERE project_id != ?", (PROJECT_ID,))
        conn.execute("DELETE FROM competitors WHERE project_id != ?", (PROJECT_ID,))

        conn.execute("DELETE FROM crawl_results WHERE task_id != ?", (TASK_ID,))
        conn.execute("DELETE FROM answer_analysis WHERE crawl_result_id NOT IN (SELECT id FROM crawl_results)")
        conn.execute("DELETE FROM mentioned_entities WHERE crawl_result_id NOT IN (SELECT id FROM crawl_results)")
        conn.execute("DELETE FROM citation_sources WHERE crawl_result_id NOT IN (SELECT id FROM crawl_results)")
        conn.execute("DELETE FROM crawl_task_logs WHERE task_id != ?", (TASK_ID,))
        conn.execute("DELETE FROM crawl_tasks WHERE id != ?", (TASK_ID,))
        conn.execute("DELETE FROM crawl_schedules WHERE id != ?", (SCHEDULE_ID,))
        conn.execute("UPDATE crawl_schedules SET status='paused' WHERE id=?", (SCHEDULE_ID,))

        conn.execute("DELETE FROM maturity_score_items WHERE report_id != ?", (REPORT_ID,))
        conn.execute("DELETE FROM maturity_reports WHERE id != ?", (REPORT_ID,))
        conn.execute("DELETE FROM usage_records WHERE task_id IS NULL OR task_id != ?", (TASK_ID,))
        conn.execute("UPDATE usage_records SET provider_test_run_id=NULL")

        for table in (
            "article_reviews",
            "article_drafts",
            "content_asset_reviews",
            "content_assets",
            "placement_records",
            "project_stage_goals",
            "delivery_package_access_logs",
            "delivery_package_shares",
            "audit_logs",
            "system_alerts",
            "queue_jobs",
            "llm_provider_test_runs",
        ):
            if table_exists(conn, table):
                conn.execute(f"DELETE FROM {table}")

        conn.execute("DELETE FROM llm_providers WHERE id != ?", (PROVIDER_ID,))
        conn.execute(
            """
            UPDATE llm_providers
            SET auth_config=?, status='inactive', updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                json.dumps(
                    {
                        "api_key_configured": False,
                        "api_key_redacted": True,
                        "requires_recipient_configuration": True,
                    },
                    ensure_ascii=False,
                ),
                PROVIDER_ID,
            ),
        )

        conn.execute("DELETE FROM users")
        conn.execute(
            """
            INSERT INTO users
                (id, company_id, name, email, phone, password_hash, role, status, last_login_at, created_at, updated_at)
            VALUES
                (1, ?, 'Handoff Admin', 'handoff-admin@local.invalid', NULL, ?, 'super_admin', 'active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (company_id, hash_password(password)),
        )

        conn.commit()
        conn.execute("VACUUM")
        conn.execute("PRAGMA foreign_keys=ON")

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]
        provider_auth = json.loads(
            conn.execute("SELECT auth_config FROM llm_providers WHERE id=?", (PROVIDER_ID,)).fetchone()[0]
        )
        mock_count = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM crawl_results cr
                JOIN llm_providers p ON p.id=cr.provider_id
                WHERE p.provider_type='mock'
                """
            ).fetchone()[0]
        )
        checks = {
            "integrity_check": integrity,
            "foreign_key_violation_count": len(fk_violations),
            "project_count": count(conn, "projects"),
            "project_1_present": count(conn, "projects", "id=1"),
            "target_question_count": count(conn, "target_questions"),
            "task_count": count(conn, "crawl_tasks"),
            "task_8_present": count(conn, "crawl_tasks", "id=8"),
            "crawl_result_count": count(conn, "crawl_results"),
            "successful_result_count": count(conn, "crawl_results", "status='success'"),
            "mock_result_count": mock_count,
            "report_count": count(conn, "maturity_reports"),
            "report_6_present": count(conn, "maturity_reports", "id=6"),
            "schedule_count": count(conn, "crawl_schedules"),
            "active_schedule_count": count(conn, "crawl_schedules", "status='active'"),
            "provider_count": count(conn, "llm_providers"),
            "active_provider_count": count(conn, "llm_providers", "status='active'"),
            "user_count": count(conn, "users"),
            "share_count": count(conn, "delivery_package_shares") if table_exists(conn, "delivery_package_shares") else 0,
            "audit_log_count": count(conn, "audit_logs") if table_exists(conn, "audit_logs") else 0,
            "provider_api_key_present": bool(provider_auth.get("api_key")),
        }
        expected = {
            "integrity_check": "ok",
            "foreign_key_violation_count": 0,
            "project_count": 1,
            "project_1_present": 1,
            "target_question_count": 25,
            "task_count": 1,
            "task_8_present": 1,
            "crawl_result_count": 100,
            "successful_result_count": 100,
            "mock_result_count": 0,
            "report_count": 1,
            "report_6_present": 1,
            "schedule_count": 1,
            "active_schedule_count": 0,
            "provider_count": 1,
            "active_provider_count": 0,
            "user_count": 1,
            "share_count": 0,
            "audit_log_count": 0,
            "provider_api_key_present": False,
        }
        mismatches = {
            key: {"expected": value, "actual": checks.get(key)}
            for key, value in expected.items()
            if checks.get(key) != value
        }
        if mismatches:
            raise RuntimeError(f"sanitized database validation failed: {mismatches}")
        return checks, password
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    db_path = output_dir / "geo_platform.project1.sanitized.db"
    backup_database(args.source_db.resolve(), db_path)
    checks, password = sanitize_database(db_path)

    restore = f"""# 项目 1 脱敏真实数据恢复说明

## 数据范围

- 项目 ID：1
- 采集任务：8
- 真实 API 回答：100 条
- 报告：6
- 周调度：1（已暂停）
- Mock 回答：0

## 安全处理

- Provider API Key 已删除，Provider 已停用。
- 周调度已暂停，避免恢复后自动调用模型。
- 原用户、密码、手机号、分享 Token、访问日志和审计日志已删除。
- 其他项目、任务和报告已删除。

## 恢复步骤

```bash
git clone https://github.com/zangqing2real-cloud/geo-optimization-platform.git
cd geo-optimization-platform
pnpm install
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
cp /path/to/geo_platform.project1.sanitized.db apps/api/geo_platform.db
./scripts/start-local.sh
./scripts/check-local.sh
```

本地登录：

- 邮箱：`handoff-admin@local.invalid`
- 初始密码：`{password}`

该账号仅用于本地交接验证。接手人应立即修改密码，并使用自己的 Provider API Key。

## 恢复后检查

1. 打开 `http://localhost:3000/projects/1`。
2. 任务 #8 应显示 100 条成功结果。
3. 报告 #6 和竞品分析说明文档应能打开。
4. Provider #10 应为未启用且没有 API Key。
5. 周调度 #1 应为暂停状态。
6. 配置接手人的 Provider Key 后，再手动测试并启用调度。

## 代码版本

Git commit：`{args.source_commit}`
"""
    (output_dir / "RESTORE.md").write_text(restore, encoding="utf-8")

    manifest = {
        "package_type": "sanitized_real_project_handoff",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": args.source_commit,
        "scope": {"project_id": PROJECT_ID, "task_id": TASK_ID, "report_id": REPORT_ID},
        "data_classification": "internal sanitized project data",
        "checks": checks,
        "warnings": [
            "API answers are real API model outputs, not browser-search evidence.",
            "Provider credentials are not included.",
            "Schedule and provider are intentionally disabled.",
        ],
    }
    (output_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checksums = []
    for file in sorted(output_dir.iterdir()):
        if file.name != "SHA256SUMS":
            checksums.append(f"{sha256(file)}  {file.name}")
    (output_dir / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    archive = output_dir.with_suffix(".tar.gz")
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(output_dir, arcname=output_dir.name)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "archive": str(archive),
                "archive_sha256": sha256(archive),
                "local_handoff_email": "handoff-admin@local.invalid",
                "local_handoff_password": password,
                "checks": checks,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
