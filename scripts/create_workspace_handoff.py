#!/usr/bin/env python3
"""Create a sanitized, non-executable SQLite handoff for one GEO workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import string
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse


HANDOFF_EMAIL = "workspace-owner@handoff.example.com"
API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
SOURCE_DB_DEFAULT = API_ROOT / "geo_platform.db"

RUNTIME_OR_SECRET_TABLES = {
    "audit_logs",
    "auth_login_throttles",
    "delivery_package_access_logs",
    "delivery_package_shares",
    "geo_local_agent_enrollments_v1",
    "geo_local_agent_nodes_v1",
    "geo_workspace_invitations_v1",
    "geo_workspace_secrets_v1",
    "llm_provider_test_runs",
    "queue_worker_heartbeats",
    "system_alerts",
}

URI_FIELDS = (
    ("geo_evidence_v1", "raw_artifact_uri", "workspace_id=?"),
    ("geo_evidence_v1", "screenshot_uri", "workspace_id=?"),
    ("geo_sampling_samples_v1", "raw_artifact_uri", "workspace_id=?"),
    ("geo_sampling_samples_v1", "screenshot_uri", "workspace_id=?"),
    ("geo_content_assets_v1", "raw_artifact_uri", "workspace_id=?"),
    ("geo_agent_artifacts_v1", "uri", "workspace_id=?"),
)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})")}


def user_foreign_keys(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        for foreign_key in conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})"):
            if foreign_key[2] == "users":
                result.append((table, foreign_key[3]))
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_password(password: str) -> str:
    iterations = 600_000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def random_password() -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "Geo-" + "".join(secrets.choice(alphabet) for _ in range(22))


def backup_database(source: Path, target: Path) -> None:
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def local_artifact_path(uri: str) -> tuple[Path, str] | None:
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        if parsed.netloc not in {"", "localhost"}:
            return None
        return Path(unquote(parsed.path)), "file_uri"
    path = Path(uri)
    if path.is_absolute():
        return path, "absolute_path"
    return None


def safe_artifact(path: Path) -> bool:
    lowered = path.name.lower()
    if lowered.startswith(".env") or lowered.endswith((".pem", ".key", ".p12", ".log")):
        return False
    if lowered in {"geo_platform.db", "geo_platform.db-wal", "geo_platform.db-shm"}:
        return False
    return path.is_file()


def collect_artifacts(
    conn: sqlite3.Connection,
    workspace_id: int,
    output_dir: Path,
) -> tuple[list[dict], list[dict]]:
    artifact_dir = output_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    exported: dict[tuple[str, str], dict] = {}
    missing: list[dict] = []
    for table, column, where in URI_FIELDS:
        if not table_exists(conn, table) or column not in table_columns(conn, table):
            continue
        query = (
            f"SELECT id, {quote_identifier(column)} FROM {quote_identifier(table)} "
            f"WHERE {where} AND {quote_identifier(column)} IS NOT NULL"
        )
        for row_id, uri in conn.execute(query, (workspace_id,)):
            resolved = local_artifact_path(str(uri))
            if resolved is None:
                continue
            source, style = resolved
            source = source.expanduser()
            if not safe_artifact(source):
                conn.execute(
                    f"UPDATE {quote_identifier(table)} SET {quote_identifier(column)}=NULL WHERE id=?",
                    (row_id,),
                )
                missing.append({"table": table, "row_id": row_id, "column": column})
                continue
            digest = sha256_file(source)
            suffix = source.suffix.lower()[:12]
            package_name = f"{digest}{suffix}"
            target = artifact_dir / package_name
            if not target.exists():
                shutil.copy2(source, target)
            key = (digest, style)
            item = exported.setdefault(
                key,
                {
                    "placeholder": f"handoff://artifact/{digest}/{style}",
                    "filename": package_name,
                    "sha256": digest,
                    "size_bytes": target.stat().st_size,
                    "style": style,
                    "references": [],
                },
            )
            item["references"].append(
                {"table": table, "row_id": row_id, "column": column}
            )
            conn.execute(
                f"UPDATE {quote_identifier(table)} SET {quote_identifier(column)}=? WHERE id=?",
                (item["placeholder"], row_id),
            )
    return list(exported.values()), missing


def project_ids_for_company(conn: sqlite3.Connection, company_id: int) -> list[int]:
    if not table_exists(conn, "projects"):
        return []
    return [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM projects WHERE company_id=? ORDER BY id", (company_id,)
        )
    ]


def delete_outside_scope(
    conn: sqlite3.Connection,
    workspace_id: int,
    company_id: int,
    project_ids: list[int],
) -> None:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        columns = table_columns(conn, table)
        if "workspace_id" in columns:
            conn.execute(
                f"DELETE FROM {quote_identifier(table)} WHERE workspace_id IS NULL OR workspace_id != ?",
                (workspace_id,),
            )
    if table_exists(conn, "geo_workspaces_v1"):
        conn.execute("DELETE FROM geo_workspaces_v1 WHERE id != ?", (workspace_id,))

    placeholders = ",".join("?" for _ in project_ids) or "NULL"
    for table in tables:
        columns = table_columns(conn, table)
        if "project_id" in columns and table != "projects":
            conn.execute(
                f"DELETE FROM {quote_identifier(table)} "
                f"WHERE project_id IS NULL OR project_id NOT IN ({placeholders})",
                project_ids,
            )

    if table_exists(conn, "projects"):
        conn.execute(
            f"DELETE FROM projects WHERE id NOT IN ({placeholders})", project_ids
        )
    if table_exists(conn, "companies"):
        conn.execute("DELETE FROM companies WHERE id != ?", (company_id,))

    dependent_filters = {
        "answer_analysis": "crawl_result_id NOT IN (SELECT id FROM crawl_results)",
        "article_reviews": "article_draft_id NOT IN (SELECT id FROM article_drafts)",
        "citation_sources": "crawl_result_id NOT IN (SELECT id FROM crawl_results)",
        "content_asset_reviews": "content_asset_id NOT IN (SELECT id FROM content_assets)",
        "geo_content_claims_v1": "content_asset_id NOT IN (SELECT id FROM geo_content_assets_v1)",
        "geo_distribution_targets_v1": "distribution_run_id NOT IN (SELECT id FROM geo_distribution_runs_v1)",
        "maturity_score_items": "report_id NOT IN (SELECT id FROM maturity_reports)",
        "mentioned_entities": "crawl_result_id NOT IN (SELECT id FROM crawl_results)",
        "observation_reviews": "crawl_result_id NOT IN (SELECT id FROM crawl_results)",
    }
    for table, where in dependent_filters.items():
        if table_exists(conn, table):
            conn.execute(f"DELETE FROM {quote_identifier(table)} WHERE {where}")

    for table in RUNTIME_OR_SECRET_TABLES:
        if table_exists(conn, table):
            if table == "llm_provider_test_runs" and table_exists(
                conn, "usage_records"
            ):
                conn.execute(
                    "UPDATE usage_records SET provider_test_run_id=NULL"
                )
            conn.execute(f"DELETE FROM {quote_identifier(table)}")


def disable_execution_and_credentials(conn: sqlite3.Connection) -> None:
    if table_exists(conn, "geo_browser_accounts_v1"):
        conn.execute(
            """
            UPDATE geo_browser_accounts_v1
            SET alias='Imported browser account ' || id, ego_task_space_id=NULL,
                status='inactive', health_note='Session removed during handoff',
                last_checked_at=NULL, last_used_at=NULL, cooldown_until=NULL,
                consecutive_failures=0, lease_token_hash=NULL, lease_worker_id=NULL,
                lease_run_id=NULL, lease_expires_at=NULL, browser_profile_alias=NULL,
                session_fingerprint=NULL, isolation_verified_at=NULL
            """
        )
    if table_exists(conn, "queue_jobs"):
        for table in (
            "geo_action_events_v1",
            "geo_agent_runs_v1",
            "geo_observation_batches_v1",
            "geo_observation_tasks_v1",
            "geo_reobservations_v1",
        ):
            if table_exists(conn, table):
                for foreign_key in conn.execute(
                    f"PRAGMA foreign_key_list({quote_identifier(table)})"
                ):
                    if foreign_key[2] == "queue_jobs":
                        conn.execute(
                            f"UPDATE {quote_identifier(table)} SET {quote_identifier(foreign_key[3])}=NULL"
                        )
        conn.execute("DELETE FROM queue_jobs")

    if table_exists(conn, "llm_providers"):
        safe_auth = json.dumps(
            {
                "api_key_configured": False,
                "api_key_redacted": True,
                "requires_recipient_configuration": True,
            },
            ensure_ascii=False,
        )
        conn.execute(
            "UPDATE llm_providers SET auth_config=?, status='inactive', updated_at=CURRENT_TIMESTAMP",
            (safe_auth,),
        )
    if table_exists(conn, "crawl_schedules"):
        conn.execute("UPDATE crawl_schedules SET status='paused', next_run_at=NULL")
    if table_exists(conn, "geo_agent_runs_v1"):
        conn.execute(
            """
            UPDATE geo_agent_runs_v1
            SET codex_thread_id=NULL, codex_turn_id=NULL, task_directory=NULL,
                status=CASE WHEN status IN ('queued','resuming','running','cancelling')
                            THEN 'cancelled' ELSE status END,
                stage=CASE WHEN status IN ('queued','resuming','running','cancelling')
                           THEN 'cancelled' ELSE stage END
            """
        )


def create_handoff_owner(
    conn: sqlite3.Connection,
    workspace_id: int,
    company_id: int,
    password: str,
) -> int:
    owner_id = 1
    for table, column in user_foreign_keys(conn):
        if table == "users" or not table_exists(conn, table):
            continue
        conn.execute(
            f"UPDATE {quote_identifier(table)} SET {quote_identifier(column)}=? "
            f"WHERE {quote_identifier(column)} IS NOT NULL",
            (owner_id,),
        )
    conn.execute("DELETE FROM users WHERE id != ?", (owner_id,))
    existing = conn.execute("SELECT 1 FROM users WHERE id=?", (owner_id,)).fetchone()
    values = (
        company_id,
        "Workspace Handoff Owner",
        HANDOFF_EMAIL,
        hash_password(password),
        "super_admin",
    )
    if existing:
        conn.execute(
            """
            UPDATE users
            SET company_id=?, name=?, email=?, phone=NULL, password_hash=?, role=?,
                status='active', last_login_at=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE id=1
            """,
            values,
        )
    else:
        conn.execute(
            """
            INSERT INTO users
                (id, company_id, name, email, phone, password_hash, role, status,
                 last_login_at, created_at, updated_at)
            VALUES (1, ?, ?, ?, NULL, ?, ?, 'active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            values,
        )
    if table_exists(conn, "geo_workspace_memberships_v1"):
        conn.execute("DELETE FROM geo_workspace_memberships_v1")
        conn.execute(
            """
            INSERT INTO geo_workspace_memberships_v1
                (workspace_id, user_id, role, status, invited_by_user_id,
                 joined_at, revoked_at, created_at, updated_at)
            VALUES (?, 1, 'owner', 'active', NULL, CURRENT_TIMESTAMP, NULL,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (workspace_id,),
        )
    return owner_id


def snapshot_counts(conn: sqlite3.Connection, workspace_id: int) -> dict[str, int]:
    result: dict[str, int] = {}
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for table in tables:
        columns = table_columns(conn, table)
        if "workspace_id" in columns:
            result[table] = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {quote_identifier(table)} WHERE workspace_id=?",
                    (workspace_id,),
                ).fetchone()[0]
            )
    return result


def migrate_copy_to_head(database: Path) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database}"
    env["AUTO_CREATE_TABLES"] = "false"
    command = [
        "uv",
        "run",
        "alembic",
        "upgrade",
        "head",
    ]
    subprocess.run(command, cwd=API_ROOT, env=env, check=True, capture_output=True, text=True)
    with sqlite3.connect(database) as conn:
        return str(conn.execute("SELECT version_num FROM alembic_version").fetchone()[0])


def finalize_sqlite_file(database: Path) -> None:
    compact = database.with_name(database.name + ".finalizing")
    if compact.exists():
        compact.unlink()
    backup_database(database, compact)
    os.replace(compact, database)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def write_importer(output_dir: Path, artifact_index: list[dict]) -> None:
    importer = '''#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, socket, sqlite3
from datetime import datetime
from pathlib import Path

def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--confirm-replace", action="store_true")
args = parser.parse_args()
root = args.repo.expanduser().resolve()
package = Path(__file__).resolve().parent
api = root / "apps" / "api"
target = api / "geo_platform.db"
if not (root / "package.json").is_file() or not api.is_dir():
    raise SystemExit("目标不是春秋元泉 GEO 仓库")
if not args.confirm_replace:
    raise SystemExit("这是数据库替换操作；确认目标为新安装后加 --confirm-replace")
if port_open(8000) or port_open(39003) or port_open(39004):
    raise SystemExit("检测到 GEO 服务端口仍在线；请先停止目标电脑上的 Web/API/Worker")

backup_root = Path.home() / ".local" / "share" / "chunqiu-yuanquan-geo" / "backups"
backup_root.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
if target.exists():
    backup = backup_root / f"before-workspace-handoff-{stamp}.db"
    with sqlite3.connect(target) as source, sqlite3.connect(backup) as dest:
        source.backup(dest)
else:
    backup = None
for suffix in ("-wal", "-shm"):
    sidecar = Path(str(target) + suffix)
    if sidecar.exists():
        shutil.move(sidecar, backup_root / f"before-workspace-handoff-{stamp}.db{suffix}")

artifact_target = api / "private_artifacts" / "handoff-workspace-1"
artifact_target.mkdir(parents=True, exist_ok=True)
index = json.loads((package / "ARTIFACT_INDEX.json").read_text(encoding="utf-8"))
temp_db = api / f".geo_platform.handoff-{stamp}.tmp.db"
shutil.copy2(package / "workspace-1.sanitized.db", temp_db)
with sqlite3.connect(temp_db) as conn:
    for item in index:
        source = package / "artifacts" / item["filename"]
        destination = artifact_target / item["filename"]
        shutil.copy2(source, destination)
        replacement = destination.resolve().as_uri() if item["style"] == "file_uri" else str(destination.resolve())
        for ref in item["references"]:
            table = '"' + ref["table"].replace('"', '""') + '"'
            column = '"' + ref["column"].replace('"', '""') + '"'
            conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (replacement, ref["row_id"]))
    conn.commit()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    if integrity != "ok" or violations:
        raise SystemExit(f"导入校验失败: integrity={integrity}, fk={len(violations)}")
temp_db.replace(target)
print(json.dumps({"database": str(target), "backup": str(backup) if backup else None,
                  "artifact_count": len(index), "login_email": "workspace-owner@handoff.example.com"},
                 ensure_ascii=False))
'''
    (output_dir / "import_workspace_handoff.py").write_text(importer, encoding="utf-8")
    (output_dir / "import_workspace_handoff.py").chmod(0o755)


def write_docs(
    output_dir: Path,
    workspace_id: int,
    source_commit: str,
    password: str,
    manifest: dict,
) -> None:
    readme = f"""# 春秋元泉 GEO 工作区 {workspace_id} 数据交接包

这是从真实数据库只读备份生成的脱敏交接包，适合导入一个全新的本地安装。

## 已包含

- 工作区 {workspace_id} 的品牌事实、问题库、观测批次、任务、证据、竞品洞察。
- 优化机会、行动、Agent 运行历史、内容版本、审核和分发记录。
- 能找到的本地证据与生成工件；文件均带 SHA-256。
- 同一公司的旧版项目数据，用于兼容旧页面。

## 已安全移除

- 原账号、密码、手机号、邀请、登录状态和审计身份。
- `.env`、Provider API Key、工作区密钥、浏览器会话、设备令牌。
- Queue Worker 心跳和可执行队列；历史任务不会自动继续执行。
- 其他工作区和其他公司数据。

## 给接收方 Codex 的导入指令

把下面一段完整发给接收方 Codex：

> 请先确认这是全新的春秋元泉 GEO 仓库，记录 `git status`、HEAD 和 39003/8000/39004 端口。完整阅读 AGENTS.md 与仓库要求，禁止读取或输出任何 `.env`。停止目标仓库的 Web、API 和 Worker 后，运行：`python /数据包绝对路径/import_workspace_handoff.py --repo /仓库绝对路径 --confirm-replace`。脚本会先把原数据库备份到用户备份目录，再导入工作区 1 和工件。随后按仓库启动说明启动服务，使用 CREDENTIALS.txt 登录，只进行只读验收：确认只有一个业务工作区、证据数量和 MANIFEST.json 一致、Provider 均为未启用、队列没有可执行历史任务。不要启用 Provider 或开始新观测，直到负责人另行确认。

## 手工导入命令

```bash
python /absolute/path/to/import_workspace_handoff.py \
  --repo /absolute/path/to/chunqiu-yuanquan-geo \
  --confirm-replace
```

导入脚本会拒绝在 8000、39003 或 39004 仍监听时运行；若目标已有数据库，会先创建可恢复备份。

## 版本

- 源代码 commit：`{source_commit}`
- 数据库迁移：`{manifest['database_revision']}`
- 生成时间：`{manifest['generated_at']}`
"""
    credentials = f"""春秋元泉 GEO 工作区 {workspace_id} 脱敏交接账号

邮箱：{HANDOFF_EMAIL}
初始密码：{password}

仅通过私密渠道传输此压缩包。首次登录后请立即修改密码，并使用接收方自己的 Provider API Key。
"""
    (output_dir / "README_导入说明.md").write_text(readme, encoding="utf-8")
    (output_dir / "CREDENTIALS.txt").write_text(credentials, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB_DEFAULT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()

    source_db = args.source_db.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise SystemExit(f"输出目录已存在，拒绝覆盖: {output_dir}")
    output_dir.mkdir(parents=True)
    database = output_dir / "workspace-1.sanitized.db"
    backup_database(source_db, database)
    password = random_password()

    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=OFF")
        workspace = conn.execute(
            "SELECT id, company_id, brand_name FROM geo_workspaces_v1 WHERE id=?",
            (args.workspace_id,),
        ).fetchone()
        if workspace is None:
            raise SystemExit(f"工作区不存在: {args.workspace_id}")
        company_id = int(workspace["company_id"])
        project_ids = project_ids_for_company(conn, company_id)
        source_counts = snapshot_counts(conn, args.workspace_id)
        artifacts, missing = collect_artifacts(conn, args.workspace_id, output_dir)
        delete_outside_scope(
            conn, args.workspace_id, company_id, project_ids
        )
        disable_execution_and_credentials(conn)
        create_handoff_owner(conn, args.workspace_id, company_id, password)
        conn.commit()
        conn.execute("VACUUM")

    database_revision = migrate_copy_to_head(database)
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        violations = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
        exported_counts = snapshot_counts(conn, args.workspace_id)
        workspace_count = int(conn.execute("SELECT COUNT(*) FROM geo_workspaces_v1").fetchone()[0])
        owner_count = int(conn.execute(
            "SELECT COUNT(*) FROM geo_workspace_memberships_v1 WHERE workspace_id=? AND role='owner' AND status='active'",
            (args.workspace_id,),
        ).fetchone()[0])
        provider_secret_count = int(conn.execute(
            "SELECT COUNT(*) FROM llm_providers WHERE auth_config LIKE '%api_key%' AND auth_config NOT LIKE '%api_key_configured%'"
        ).fetchone()[0])
        queue_count = int(conn.execute("SELECT COUNT(*) FROM queue_jobs").fetchone()[0])
        checks = {
            "integrity_check": integrity,
            "foreign_key_violation_count": len(violations),
            "workspace_count": workspace_count,
            "active_owner_count": owner_count,
            "provider_secret_count": provider_secret_count,
            "executable_queue_row_count": queue_count,
        }
        if checks != {
            "integrity_check": "ok",
            "foreign_key_violation_count": 0,
            "workspace_count": 1,
            "active_owner_count": 1,
            "provider_secret_count": 0,
            "executable_queue_row_count": 0,
        }:
            raise RuntimeError(f"交接数据库校验失败: {checks}")
    finalize_sqlite_file(database)

    artifact_index = sorted(artifacts, key=lambda item: item["filename"])
    (output_dir / "ARTIFACT_INDEX.json").write_text(
        json.dumps(artifact_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "package_type": "sanitized_geo_workspace_handoff",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": args.source_commit,
        "database_revision": database_revision,
        "scope": {
            "workspace_id": args.workspace_id,
            "company_id": company_id,
            "project_ids": project_ids,
            "brand_name": workspace["brand_name"],
        },
        "source_workspace_counts": source_counts,
        "exported_workspace_counts": exported_counts,
        "artifact_file_count": len(artifact_index),
        "artifact_reference_count": sum(len(item["references"]) for item in artifact_index),
        "missing_or_excluded_artifact_references": missing,
        "checks": checks,
        "safety": {
            "provider_credentials_included": False,
            "original_accounts_included": False,
            "workspace_secrets_included": False,
            "browser_sessions_included": False,
            "executable_queue_included": False,
            "other_workspaces_included": False,
        },
    }
    (output_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_importer(output_dir, artifact_index)
    write_docs(output_dir, args.workspace_id, args.source_commit, password, manifest)

    checksums = []
    package_files = sorted(
        item
        for item in output_dir.rglob("*")
        if item.is_file() and not item.name.endswith((".db-wal", ".db-shm"))
    )
    for path in package_files:
        relative = path.relative_to(output_dir)
        if relative.name == "SHA256SUMS":
            continue
        checksums.append(f"{sha256_file(path)}  {relative}")
    (output_dir / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    archive = output_dir.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in package_files:
            bundle.write(path, Path(output_dir.name) / path.relative_to(output_dir))
    print(json.dumps({
        "output_dir": str(output_dir),
        "archive": str(archive),
        "archive_sha256": sha256_file(archive),
        "manifest": manifest,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
