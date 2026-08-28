"""Recurring observation plans and deterministic change-alert evaluation."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import (
    GeoChangeAlert,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationSchedule,
    GeoObservationScheduleRun,
    GeoObservationTask,
)
from app.v1.action_retests import build_batch_metrics


ALERT_COOLDOWN = timedelta(hours=24)


def canonical_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def schedule_scope(provider_ids: list[int], question_ids: list[int], repeat_count: int) -> dict:
    return {
        "schema": "geo-observation-scope/v1",
        "provider_ids": sorted(set(provider_ids)),
        "question_plan_ids": sorted(set(question_ids)),
        "repeat_count": repeat_count,
    }


def next_schedule_time(
    *, cadence: str, weekdays: list[int], local_time: str, timezone_name: str,
    after: datetime | None = None,
) -> datetime:
    zone = ZoneInfo(timezone_name)
    source = after or datetime.now(UTC)
    # SQLite returns stored UTC timestamps without tzinfo. Treating that value
    # as the host's local time can calculate the same window forever (for
    # example 01:00 UTC becomes 01:00 Asia/Shanghai and maps back to 01:00 UTC).
    # The persistence contract is UTC, so normalize naive values at this edge.
    if source.tzinfo is None:
        source = source.replace(tzinfo=UTC)
    cursor = source.astimezone(zone)
    hour, minute = (int(value) for value in local_time.split(":"))
    allowed = set(weekdays or ([cursor.weekday()] if cadence == "weekly" else range(7)))
    for offset in range(0, 15):
        candidate = (cursor + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate.weekday() in allowed and candidate > cursor:
            return candidate.astimezone(UTC)
    raise ValueError("无法计算下一次运行时间")


def schedule_window_key(schedule: GeoObservationSchedule, scheduled_for: datetime) -> str:
    local = scheduled_for.astimezone(ZoneInfo(schedule.timezone_name))
    return f"{schedule.scope_version}:{local.strftime('%Y-%m-%dT%H:%M')}"


def _scope_matches(batch: GeoObservationBatch, scope: dict) -> bool:
    config = batch.configuration or {}
    providers = sorted(
        int(item.get("id") or 0)
        for item in config.get("providers") or []
        if isinstance(item, dict) and int(item.get("id") or 0) > 0
    )
    questions = sorted(
        int(item.get("id") or 0)
        for item in config.get("questions") or []
        if isinstance(item, dict) and int(item.get("id") or 0) > 0
    )
    return (
        providers == sorted(scope.get("provider_ids") or [])
        and questions == sorted(scope.get("question_plan_ids") or [])
        and int(batch.repeat_count or 0) == int(scope.get("repeat_count") or 0)
    )


def latest_comparable_batch(
    db: Session, *, workspace_id: int, scope: dict, before_batch_id: int | None = None
) -> GeoObservationBatch | None:
    rows = list(
        db.scalars(
            select(GeoObservationBatch)
            .where(
                GeoObservationBatch.workspace_id == workspace_id,
                GeoObservationBatch.status.in_(("completed", "success")),
            )
            .order_by(GeoObservationBatch.id.desc())
        )
    )
    return next(
        (row for row in rows if row.id != before_batch_id and _scope_matches(row, scope)), None
    )


def evidence_snapshot(db: Session, batch: GeoObservationBatch) -> dict:
    tasks = list(
        db.scalars(
            select(GeoObservationTask)
            .where(GeoObservationTask.batch_id == batch.id)
            .order_by(GeoObservationTask.id)
        )
    )
    evidence_ids = [int(task.evidence_id) for task in tasks if task.evidence_id]
    evidence = list(
        db.scalars(select(GeoEvidence).where(GeoEvidence.id.in_(evidence_ids or [-1])))
    )
    domains: Counter[str] = Counter()
    competitors: Counter[str] = Counter()
    for row in evidence:
        for item in row.source_items or []:
            if isinstance(item, dict):
                host = urlsplit(str(item.get("url") or "")).hostname
                if host:
                    domains[host.lower()] += 1
        for item in row.competitor_positions or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("name") or item.get("entity") or item.get("brand") or "").strip()
            if key:
                competitors[key] += 1
    failed = sum(task.status == "failed" for task in tasks)
    empty = sum(
        task.status in {"completed", "succeeded"} and not task.evidence_id for task in tasks
    )
    return {
        "evidence_ids": evidence_ids,
        "source_counts": dict(domains.most_common(30)),
        "competitor_counts": dict(competitors.most_common(30)),
        "failed_tasks": failed,
        "empty_tasks": empty,
        "total_tasks": len(tasks),
    }


def _existing_active_alert(db: Session, workspace_id: int, dedupe_key: str) -> GeoChangeAlert | None:
    now = datetime.now(UTC)
    rows = list(
        db.scalars(
            select(GeoChangeAlert)
            .where(
                GeoChangeAlert.workspace_id == workspace_id,
                GeoChangeAlert.dedupe_key == dedupe_key,
                GeoChangeAlert.status.in_(("open", "confirmed")),
            )
            .order_by(GeoChangeAlert.id.desc())
        )
    )
    def is_cooling_down(row: GeoChangeAlert) -> bool:
        if row.cooldown_until is None:
            return True
        until = row.cooldown_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return until > now

    return next((row for row in rows if is_cooling_down(row)), None)


def evaluate_change_alerts(
    db: Session, *, run: GeoObservationScheduleRun, current: GeoObservationBatch,
    baseline: GeoObservationBatch | None,
) -> list[GeoChangeAlert]:
    current_metrics = build_batch_metrics(db, current)
    current_aux = evidence_snapshot(db, current)
    current_complete = (
        int(current_metrics.get("expected_samples") or 0) > 0
        and current_metrics.get("eligible_samples") == current_metrics.get("expected_samples")
    )
    candidates: list[dict] = []
    baseline_metrics = build_batch_metrics(db, baseline) if baseline else None
    baseline_aux = evidence_snapshot(db, baseline) if baseline else None
    baseline_complete = bool(
        baseline_metrics
        and int(baseline_metrics.get("expected_samples") or 0) > 0
        and baseline_metrics.get("eligible_samples") == baseline_metrics.get("expected_samples")
    )
    completeness = {
        "baseline_complete": baseline_complete,
        "current_complete": current_complete,
        "baseline_eligible": int((baseline_metrics or {}).get("eligible_samples") or 0),
        "current_eligible": int(current_metrics.get("eligible_samples") or 0),
        "expected": int(current_metrics.get("expected_samples") or 0),
    }
    if not baseline or not baseline_complete or not current_complete:
        candidates.append({
            "type": "observation.incomplete",
            "severity": "warning",
            "title": "本轮观测样本不完整",
            "summary": "本轮数据只作为观测异常处理，不判断品牌升降。",
            "metric": {"completeness": completeness},
            "suggested": {"action_type": "observation_recovery", "label": "检查失败任务"},
        })
    else:
        before_rate = float(baseline_metrics.get("mention_rate") or 0)
        after_rate = float(current_metrics.get("mention_rate") or 0)
        delta = round(after_rate - before_rate, 4)
        if delta <= -0.1:
            candidates.append({
                "type": "brand.visibility_drop",
                "severity": "critical" if delta <= -0.2 else "warning",
                "title": "品牌可见度下降",
                "summary": f"品牌可见度从 {before_rate:.0%} 降至 {after_rate:.0%}",
                "metric": {"baseline": before_rate, "current": after_rate, "delta": delta},
                "suggested": {"action_type": "article", "label": "创建品牌可见度优化行动"},
            })
        before_comp = (baseline_aux or {}).get("competitor_counts") or {}
        after_comp = current_aux.get("competitor_counts") or {}
        for name, after_count in sorted(after_comp.items()):
            before_count = int(before_comp.get(name) or 0)
            if int(after_count) >= before_count + 2 and int(after_count) > int(current_metrics.get("positive_count") or 0):
                candidates.append({
                    "type": "competitor.overtake",
                    "severity": "critical",
                    "title": f"竞品 {name} 在当前范围反超",
                    "summary": f"竞品出现次数从 {before_count} 增至 {after_count}",
                    "metric": {"competitor": name, "baseline": before_count, "current": after_count},
                    "suggested": {"action_type": "official_site", "label": "创建竞品差距行动"},
                })
                break
        before_sources = (baseline_aux or {}).get("source_counts") or {}
        after_sources = current_aux.get("source_counts") or {}
        changed = [
            {"domain": domain, "baseline": int(before_sources.get(domain) or 0), "current": int(count)}
            for domain, count in after_sources.items()
            if int(count) >= int(before_sources.get(domain) or 0) + 2
        ]
        if changed:
            candidates.append({
                "type": "source.weight_shift",
                "severity": "info",
                "title": "重要信源引用权重变化",
                "summary": f"{changed[0]['domain']} 的引用次数明显增加",
                "metric": {"changes": changed[:5]},
                "suggested": {"action_type": "third_party_source", "label": "创建信源建设行动"},
            })
    total = max(int(current_aux.get("total_tasks") or 0), 1)
    failure_rate = (
        int(current_aux.get("failed_tasks") or 0) + int(current_aux.get("empty_tasks") or 0)
    ) / total
    if failure_rate >= 0.3:
        candidates.append({
            "type": "model.failure_rate",
            "severity": "critical" if failure_rate >= 0.5 else "warning",
            "title": "模型观测连续失败或返回空结果",
            "summary": f"本轮失败或空结果占 {failure_rate:.0%}",
            "metric": {"failure_rate": round(failure_rate, 4), **current_aux},
            "suggested": {"action_type": "observation_recovery", "label": "检查模型与采集服务"},
        })

    created: list[GeoChangeAlert] = []
    now = datetime.now(UTC)
    for candidate in candidates:
        dedupe_key = f"{candidate['type']}:{run.scope_fingerprint}"
        if _existing_active_alert(db, run.workspace_id, dedupe_key):
            continue
        row = GeoChangeAlert(
            workspace_id=run.workspace_id,
            schedule_run_id=run.id,
            alert_type=candidate["type"],
            severity=candidate["severity"],
            status="open",
            title=candidate["title"],
            summary=candidate["summary"],
            dedupe_key=dedupe_key,
            baseline_batch_id=baseline.id if baseline else None,
            current_batch_id=current.id,
            scope_snapshot=run.scope_snapshot,
            completeness=completeness,
            metric_snapshot=candidate["metric"],
            evidence_ids=current_aux["evidence_ids"],
            suggested_action=candidate["suggested"],
            cooldown_until=now + ALERT_COOLDOWN,
        )
        db.add(row)
        db.flush()
        created.append(row)
    run.status = "evaluated"
    run.completed_at = now
    run.baseline_batch_id = baseline.id if baseline else None
    db.add(run)
    return created
