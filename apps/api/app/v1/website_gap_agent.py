"""Codex-backed official-site gap analysis over one frozen observation scope."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import QueueJob
from app.models.cleanroom_v1 import (
    GeoActionEvent,
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoEvidence,
    GeoObservationTask,
    GeoWebsiteAudit,
)
from app.services.codex_agent_runtime import LocalCodexRuntime
from app.v1.action_opportunities import _fingerprint, _source_url
from app.v1.opportunity_agent import build_opportunity_context


WEBSITE_GAP_RULE_VERSION = "codex-website-gap.v1"
WEBSITE_GAP_JOB_TYPE = "geo_website_gap.analyze"
SKILL_NAME = "cqyq-geo-official-site-gap-analysis"
SKILL_ROOT = Path(__file__).resolve().parents[1] / "agent_skills" / SKILL_NAME
ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[2]
    / "private_artifacts"
    / "website-gap-analysis"
)
POSITIVE_BRAND_STATUSES = {"mentioned", "shortlisted", "recommended", "cited"}


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_contract": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "sha256": {"type": "string"},
            },
            "required": ["name", "sha256"],
            "additionalProperties": False,
        },
        "analysis_summary": {"type": "string"},
        "confidence": {"type": "number"},
        "official_performance": {
            "type": "object",
            "properties": {
                "interpretation": {"type": "string"},
                "content_use_status": {
                    "type": "string",
                    "enum": ["supported", "not_supported", "not_measurable"],
                },
            },
            "required": ["interpretation", "content_use_status"],
            "additionalProperties": False,
        },
        "competitor_content_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                    "affected_models": {"type": "array", "items": {"type": "string"}},
                    "affected_question_plan_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "source_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Copy each value byte-for-byte from INPUT_CONTEXT.observed_source_urls."
                        ),
                    },
                },
                "required": [
                    "theme",
                    "why_it_matters",
                    "evidence_ids",
                    "affected_models",
                    "affected_question_plan_ids",
                    "source_urls",
                ],
                "additionalProperties": False,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "title": {"type": "string"},
                    "target_page": {"type": "string"},
                    "required_content": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                    "affected_models": {"type": "array", "items": {"type": "string"}},
                    "affected_question_plan_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "source_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Copy each value byte-for-byte from INPUT_CONTEXT.observed_source_urls; "
                            "target_page is not a source URL."
                        ),
                    },
                },
                "required": [
                    "priority",
                    "title",
                    "target_page",
                    "required_content",
                    "reason",
                    "evidence_ids",
                    "affected_models",
                    "affected_question_plan_ids",
                    "source_urls",
                ],
                "additionalProperties": False,
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "skill_contract",
        "analysis_summary",
        "confidence",
        "official_performance",
        "competitor_content_gaps",
        "recommendations",
        "limitations",
    ],
    "additionalProperties": False,
}


def _host(value: str | None) -> str:
    try:
        return (urlsplit(str(value or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _host_matches(host: str, domain: str) -> bool:
    return bool(host and domain and (host == domain or host.endswith(f".{domain}")))


def load_skill_contract() -> dict:
    files = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "references" / "metric-contract.md",
        SKILL_ROOT / "references" / "output-contract.md",
    ]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise ValueError(f"Required website analysis Skill is incomplete: {', '.join(missing)}")
    skill_text = files[0].read_text(encoding="utf-8")
    if f"name: {SKILL_NAME}" not in skill_text:
        raise ValueError("Required website analysis Skill has an unexpected name")
    documents = [
        {"path": str(path.relative_to(SKILL_ROOT)), "content": path.read_text(encoding="utf-8")}
        for path in files
    ]
    canonical = json.dumps(documents, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "name": SKILL_NAME,
        "sha256": sha256(canonical.encode("utf-8")).hexdigest(),
        "documents": documents,
    }


def build_website_gap_context(
    db: Session,
    workspace_id: int,
    *,
    batch_id: int,
    model_keys: Iterable[str] | None = None,
    question_plan_ids: Iterable[int] | None = None,
    skill_contract: dict | None = None,
) -> dict:
    skill = skill_contract or load_skill_contract()
    base = build_opportunity_context(
        db,
        workspace_id,
        batch_id=batch_id,
        model_keys=model_keys,
        question_plan_ids=question_plan_ids,
    )
    official_host = _host(base["workspace"].get("official_website"))
    if not official_host:
        raise ValueError("Workspace official website is not configured")

    resolved_models = sorted({str(row["model_key"]) for row in base["evidence"]})
    resolved_questions = sorted({int(row["question_plan_id"]) for row in base["evidence"]})
    eligible_ids = [int(row["evidence_id"]) for row in base["evidence"]]
    official_cited_ids: list[int] = []
    brand_mentioned_ids: list[int] = []
    other_domains: Counter[str] = Counter()
    observed_urls: set[str] = set()

    for row in base["evidence"]:
        official_urls: list[str] = []
        for source in row.get("sources") or []:
            url = str(source.get("url") or "")
            if not url:
                continue
            observed_urls.add(url)
            source["is_official"] = _host_matches(_host(url), official_host)
            if source["is_official"]:
                official_urls.append(url)
            elif _host(url):
                other_domains[_host(url)] += 1
        row["official_source_urls"] = official_urls
        if official_urls:
            official_cited_ids.append(int(row["evidence_id"]))
        if str(row.get("brand_status") or "") in POSITIVE_BRAND_STATUSES:
            brand_mentioned_ids.append(int(row["evidence_id"]))

    latest_audit = db.scalar(
        select(GeoWebsiteAudit)
        .where(GeoWebsiteAudit.workspace_id == workspace_id)
        .order_by(GeoWebsiteAudit.checked_at.desc(), GeoWebsiteAudit.id.desc())
        .limit(1)
    )
    audit_snapshot = None
    if latest_audit is not None:
        audit_snapshot = {
            "id": latest_audit.id,
            "status": latest_audit.status,
            "score": latest_audit.score,
            "audit_version": latest_audit.audit_version,
            "raw_html_sha256": latest_audit.raw_html_sha256,
            "finding_codes": [
                str(item.get("code") or "")
                for item in (latest_audit.findings or [])
                if isinstance(item, dict) and item.get("code")
            ],
            "checked_at": latest_audit.checked_at.isoformat(),
        }

    total = len(eligible_ids)
    deterministic_metrics = {
        "eligible_answer_count": total,
        "brand_mentioned_answer_count": len(brand_mentioned_ids),
        "brand_mention_rate": round(len(brand_mentioned_ids) / total, 4),
        "official_cited_answer_count": len(official_cited_ids),
        "official_citation_rate": round(len(official_cited_ids) / total, 4),
        "official_cited_evidence_ids": official_cited_ids,
        "content_use_status": "not_measurable",
        "other_source_domains": [
            {"domain": domain, "answer_source_count": count}
            for domain, count in other_domains.most_common(12)
        ],
    }
    scope_manifest = {
        "workspace_id": workspace_id,
        "batch_id": batch_id,
        "requested_model_keys": sorted({str(value).strip() for value in (model_keys or []) if str(value).strip()}),
        "requested_question_plan_ids": sorted({int(value) for value in (question_plan_ids or [])}),
        "resolved_model_keys": resolved_models,
        "resolved_question_plan_ids": resolved_questions,
        "eligible_evidence_ids": eligible_ids,
        "answer_hashes": {str(row["evidence_id"]): row["answer_hash"] for row in base["evidence"]},
    }
    input_fingerprint = sha256(
        json.dumps(
            {
                "base_input_fingerprint": base["input_fingerprint"],
                "scope_manifest": scope_manifest,
                "official_host": official_host,
                "website_audit": audit_snapshot,
                "skill_sha256": skill["sha256"],
                "rule_version": WEBSITE_GAP_RULE_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "geo-website-gap-analysis.v1",
        "workspace": {
            **base["workspace"],
            "official_host": official_host,
        },
        "scope_manifest": scope_manifest,
        "input_fingerprint": input_fingerprint,
        "evidence_gate": base["evidence_gate"],
        "deterministic_metrics": deterministic_metrics,
        "latest_technical_audit": audit_snapshot,
        "observed_source_urls": sorted(observed_urls),
        "evidence": base["evidence"],
        "skill_contract": {"name": skill["name"], "sha256": skill["sha256"]},
    }


def _developer_instructions(skill: dict) -> str:
    rendered = "\n\n".join(
        f"--- {document['path']} ---\n{document['content']}" for document in skill["documents"]
    )
    return f"""You are the official-site gap analyst for 春秋元泉 GEO. The following Skill is a
mandatory execution contract injected by the backend. Follow every rule. Do not inspect local files,
databases, credentials, browser profiles, or other batches. Do not edit, publish, or generate an article.
Return only JSON matching the supplied schema.

MANDATORY_SKILL_CONTRACT
name={skill['name']}
sha256={skill['sha256']}

{rendered}
"""


def _prompt(context: dict) -> str:
    return """Analyze only this frozen GEO observation scope. Explain where the official website is
underrepresented, which competitor content patterns appear in the same answers, and what concrete
official-site content should be added or improved. The backend metrics are authoritative; do not alter
their counts. A brand mention is not an official citation. If supplied evidence cannot prove content
absorption, return not_measurable. Every gap and recommendation must use exact evidence IDs and exact
source URLs from the context. Generic SEO/GEO advice without an observed gap is forbidden.
For every source_urls array, copy values byte-for-byte from INPUT_CONTEXT.observed_source_urls.
Never place a proposed target page or the configured official website in source_urls unless that exact
string already appears in INPUT_CONTEXT.observed_source_urls. Use target_page for proposed destinations.

INPUT_CONTEXT:
""" + json.dumps(context, ensure_ascii=False, indent=2)


def _validated_items(context: dict, parsed: dict, field: str) -> list[dict]:
    allowed_evidence = set(context["scope_manifest"]["eligible_evidence_ids"])
    allowed_models = set(context["scope_manifest"]["resolved_model_keys"])
    allowed_questions = set(context["scope_manifest"]["resolved_question_plan_ids"])
    allowed_urls = set(context["observed_source_urls"])
    validated = []
    for raw in parsed.get(field) or []:
        evidence_ids = list(dict.fromkeys(int(value) for value in raw.get("evidence_ids") or []))
        models = list(dict.fromkeys(str(value) for value in raw.get("affected_models") or []))
        questions = list(
            dict.fromkeys(int(value) for value in raw.get("affected_question_plan_ids") or [])
        )
        urls = list(dict.fromkeys(str(value) for value in raw.get("source_urls") or []))
        if not evidence_ids or any(value not in allowed_evidence for value in evidence_ids):
            raise ValueError(f"Codex {field} contains evidence outside the frozen scope")
        if any(value not in allowed_models for value in models):
            raise ValueError(f"Codex {field} contains a model outside the frozen scope")
        if any(value not in allowed_questions for value in questions):
            raise ValueError(f"Codex {field} contains a question outside the frozen scope")
        if any(value not in allowed_urls for value in urls):
            raise ValueError(f"Codex {field} contains an unobserved source URL")
        validated.append(
            {
                **raw,
                "evidence_ids": evidence_ids,
                "affected_models": models,
                "affected_question_plan_ids": questions,
                "source_urls": urls,
            }
        )
    return validated[:12]


def validate_result(context: dict, parsed: dict) -> dict:
    expected_skill = context["skill_contract"]
    if parsed.get("skill_contract") != expected_skill:
        raise ValueError("Codex did not acknowledge the mandatory website analysis Skill")
    confidence = float(parsed.get("confidence") or 0)
    if not 0 <= confidence <= 1:
        raise ValueError("Codex website analysis confidence is outside 0..1")
    performance = parsed.get("official_performance") or {}
    if performance.get("content_use_status") not in {
        "supported",
        "not_supported",
        "not_measurable",
    }:
        raise ValueError("Codex returned an invalid official content-use status")
    return {
        **parsed,
        "analysis_summary": str(parsed.get("analysis_summary") or "").strip()[:4000],
        "confidence": confidence,
        "official_performance": {
            "interpretation": str(performance.get("interpretation") or "").strip()[:4000],
            "content_use_status": performance["content_use_status"],
        },
        "competitor_content_gaps": _validated_items(context, parsed, "competitor_content_gaps"),
        "recommendations": _validated_items(context, parsed, "recommendations"),
        "limitations": [str(value).strip()[:1000] for value in parsed.get("limitations") or [] if str(value).strip()][:12],
    }


def materialize_website_gap_opportunity(
    db: Session,
    *,
    job: QueueJob,
    context: dict,
    result: dict,
) -> GeoActionOpportunity | None:
    recommendations = result["recommendations"]
    if not recommendations:
        return None
    scope = context["scope_manifest"]
    used_ids = sorted(
        {
            int(value)
            for item in [*recommendations, *result["competitor_content_gaps"]]
            for value in item["evidence_ids"]
        }
    )
    evidence_by_id = {
        row.id: row
        for row in db.scalars(select(GeoEvidence).where(GeoEvidence.id.in_(used_ids or [-1])))
        if row.workspace_id == scope["workspace_id"]
    }
    if set(used_ids) != set(evidence_by_id):
        raise ValueError("Website gap evidence disappeared before materialization")
    task_by_evidence = {
        int(task.evidence_id): task
        for task in db.scalars(
            select(GeoObservationTask).where(
                GeoObservationTask.workspace_id == scope["workspace_id"],
                GeoObservationTask.batch_id == scope["batch_id"],
                GeoObservationTask.evidence_id.in_(used_ids or [-1]),
            )
        )
        if task.evidence_id
    }
    requested_scope = {
        "batch_id": scope["batch_id"],
        "model_keys": scope["requested_model_keys"],
        "question_plan_ids": scope["requested_question_plan_ids"],
    }
    for existing in db.scalars(
        select(GeoActionOpportunity).where(
            GeoActionOpportunity.workspace_id == scope["workspace_id"],
            GeoActionOpportunity.opportunity_type == "website_scope_gap",
            GeoActionOpportunity.status == "open",
        )
    ):
        snapshot = existing.scope_snapshot or {}
        if all(snapshot.get(key) == value for key, value in requested_scope.items()):
            existing.status = "stale"

    priority_rank = {"high": 3, "medium": 2, "low": 1}
    priority = max(
        (str(item.get("priority") or "low") for item in recommendations),
        key=lambda value: priority_rank.get(value, 0),
    )
    first = recommendations[0]
    fingerprint = _fingerprint(
        scope["workspace_id"],
        context["input_fingerprint"],
        WEBSITE_GAP_RULE_VERSION,
    )
    audit = context.get("latest_technical_audit") or {}
    snapshot = {
        **requested_scope,
        "source_type": "model_observation",
        "analysis_kind": "official_site_gap",
        "resolved_model_keys": scope["resolved_model_keys"],
        "resolved_question_plan_ids": scope["resolved_question_plan_ids"],
        "eligible_evidence_ids": scope["eligible_evidence_ids"],
        "input_fingerprint": context["input_fingerprint"],
        "discovery_job_id": job.id,
        "codex_thread_id": (job.payload_json or {}).get("codex_thread_id"),
        "codex_turn_id": (job.payload_json or {}).get("codex_turn_id"),
        "skill_contract": context["skill_contract"],
        "official_metrics": context["deterministic_metrics"],
        "official_performance": result["official_performance"],
        "recommendations": recommendations,
        "competitor_content_gaps": result["competitor_content_gaps"],
        "agent_confidence": result["confidence"],
        "agent_rationale": result["analysis_summary"],
        "missing_content": list(dict.fromkeys(
            str(value)
            for item in recommendations
            for value in item.get("required_content") or []
            if str(value).strip()
        ))[:20],
        "competitor_content_patterns": [
            str(item.get("theme") or "") for item in result["competitor_content_gaps"]
            if str(item.get("theme") or "").strip()
        ],
        "uncertainties": result["limitations"],
        "source_strategy": "official_site_handoff",
        "primary_source": {
            "url": context["workspace"]["official_website"],
            "host": context["workspace"]["official_host"],
            "platform_key": "official_site",
            "controllability": "owned",
        },
        "recommended_carrier": "官网内容整改建议",
        "website_audit_id": audit.get("id"),
        "website_audit_status": audit.get("status"),
        "raw_html_sha256": audit.get("raw_html_sha256"),
    }
    question_id = scope["resolved_question_plan_ids"][0] if len(scope["resolved_question_plan_ids"]) == 1 else None
    if question_id:
        snapshot["question_plan_id"] = question_id
        question = next(
            (row["question"] for row in context["evidence"] if int(row["question_plan_id"]) == question_id),
            "",
        )
        snapshot["question"] = question
    opportunity = db.scalar(
        select(GeoActionOpportunity).where(
            GeoActionOpportunity.workspace_id == scope["workspace_id"],
            GeoActionOpportunity.fingerprint == fingerprint,
        )
    )
    values = {
        "opportunity_type": "website_scope_gap",
        "title": f"官网差距：{str(first.get('title') or '补齐选定范围的官网内容')[:220]}",
        "summary": result["analysis_summary"],
        "priority_score": {"high": 90.0, "medium": 70.0, "low": 50.0}[priority],
        "priority_label": priority,
        "evidence_strength": result["confidence"],
        "source_gap_type": "official_site_scope_gap",
        "recommended_asset_type": "website_recommendation",
        "recommended_platforms": ["official_site"],
        "scope_snapshot": snapshot,
        "rule_version": WEBSITE_GAP_RULE_VERSION,
        "latest_seen_batch_id": scope["batch_id"],
    }
    if opportunity is None:
        opportunity = GeoActionOpportunity(
            workspace_id=scope["workspace_id"],
            fingerprint=fingerprint,
            status="open",
            first_seen_batch_id=scope["batch_id"],
            **values,
        )
        db.add(opportunity)
        db.flush()
    elif opportunity.status not in {"selected", "completed", "dismissed"}:
        for key, value in values.items():
            setattr(opportunity, key, value)
        opportunity.status = "open"
    for evidence_id in used_ids:
        if db.scalar(
            select(GeoActionOpportunityEvidence).where(
                GeoActionOpportunityEvidence.opportunity_id == opportunity.id,
                GeoActionOpportunityEvidence.evidence_id == evidence_id,
            )
        ):
            continue
        evidence = evidence_by_id[evidence_id]
        task = task_by_evidence.get(evidence_id)
        first_url = next(
            (_source_url(source) for source in (evidence.source_items or []) if _source_url(source)),
            None,
        )
        db.add(
            GeoActionOpportunityEvidence(
                opportunity_id=opportunity.id,
                workspace_id=scope["workspace_id"],
                batch_id=scope["batch_id"],
                observation_task_id=task.id if task else None,
                evidence_id=evidence.id,
                question_plan_id=evidence.question_plan_id,
                provider_id=task.provider_id if task else None,
                model_key=evidence.model_key,
                signal_type="official_site_scope_gap",
                signal_value={
                    "official_cited": evidence_id
                    in context["deterministic_metrics"]["official_cited_evidence_ids"],
                    "analysis_job_id": job.id,
                },
                evidence_hash=evidence.answer_hash,
                source_url=first_url,
            )
        )
    db.add(
        GeoActionEvent(
            workspace_id=scope["workspace_id"],
            job_id=job.id,
            event_type="website_gap_analysis_completed",
            actor_type="worker",
            detail={
                "opportunity_id": opportunity.id,
                "batch_id": scope["batch_id"],
                "model_keys": scope["requested_model_keys"],
                "question_plan_ids": scope["requested_question_plan_ids"],
                "skill_contract": context["skill_contract"],
                "evidence_count": len(used_ids),
            },
        )
    )
    db.flush()
    return opportunity


def execute_website_gap_analysis(
    db: Session,
    job: QueueJob,
    *,
    runtime: LocalCodexRuntime | None = None,
) -> dict:
    payload = dict(job.payload_json or {})
    skill = load_skill_contract()
    if payload.get("skill_sha256") != skill["sha256"] or payload.get("skill_name") != skill["name"]:
        raise ValueError("Mandatory website analysis Skill changed before execution; start a new run")
    context = build_website_gap_context(
        db,
        int(payload["workspace_id"]),
        batch_id=int(payload["batch_id"]),
        model_keys=payload.get("model_keys") or [],
        question_plan_ids=payload.get("question_plan_ids") or [],
        skill_contract=skill,
    )
    if payload.get("input_fingerprint") != context["input_fingerprint"]:
        raise ValueError("Website analysis inputs changed before Codex began; start a new run")

    task_directory = ARTIFACT_ROOT / str(payload["workspace_id"]) / str(job.id)
    task_directory.mkdir(parents=True, exist_ok=True)
    context_path = task_directory / "input.json"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    job.payload_json = {**payload, "stage": "analyzing", "evidence_count": len(context["evidence"])}
    db.add(job)
    db.commit()

    runtime = runtime or LocalCodexRuntime()

    def on_started(thread_id: str, turn_id: str) -> None:
        job.payload_json = {
            **dict(job.payload_json or {}),
            "stage": "analyzing",
            "codex_thread_id": thread_id,
            "codex_turn_id": turn_id,
        }
        db.add(job)
        db.commit()

    turn = runtime.run_structured(
        task_directory=task_directory,
        prompt=_prompt(context),
        output_schema=OUTPUT_SCHEMA,
        developer_instructions=_developer_instructions(skill),
        model=payload.get("model"),
        reasoning_effort=payload.get("reasoning_effort"),
        on_started=on_started,
        timeout_seconds=max(60, min(int(get_settings().agent_run_timeout_seconds), 3600)),
    )
    raw_result_path = task_directory / "raw_result.json"
    raw_result_path.write_text(turn.final_response, encoding="utf-8")
    parsed = validate_result(context, json.loads(turn.final_response))
    result_path = task_directory / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "result": parsed,
                "deterministic_metrics": context["deterministic_metrics"],
                "usage": turn.usage,
                "codex_thread_id": turn.thread_id,
                "codex_turn_id": turn.turn_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    recommendations = [
        {
            "priority": item["priority"],
            "title": str(item["title"])[:220],
            "target_page": str(item["target_page"])[:500],
            "required_content": [str(value)[:500] for value in item["required_content"][:12]],
            "reason": str(item["reason"])[:2000],
            "evidence_ids": item["evidence_ids"],
            "affected_models": item["affected_models"],
            "affected_question_plan_ids": item["affected_question_plan_ids"],
            "source_urls": item["source_urls"],
        }
        for item in parsed["recommendations"]
    ]
    db.add(
        GeoActionEvent(
            workspace_id=int(payload["workspace_id"]),
            job_id=job.id,
            event_type="website_gap_analysis_completed",
            actor_type="worker",
            detail={
                "opportunity_id": None,
                "batch_id": int(payload["batch_id"]),
                "model_keys": list(payload.get("model_keys") or []),
                "question_plan_ids": list(payload.get("question_plan_ids") or []),
                "skill_contract": context["skill_contract"],
                "evidence_count": len(context["evidence"]),
                "recommendation_count": len(recommendations),
                "result_kind": "independent_website_diagnostic",
            },
        )
    )
    job.payload_json = {
        **dict(job.payload_json or {}),
        "stage": "complete",
        "result_count": 1 if recommendations else 0,
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
        "analysis_summary": parsed["analysis_summary"][:1000],
        "official_metrics": context["deterministic_metrics"],
        "codex_thread_id": turn.thread_id,
        "codex_turn_id": turn.turn_id,
        "result_sha256": sha256(result_path.read_bytes()).hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add(job)
    db.commit()
    return {
        "stage": "complete",
        "result_count": 1 if recommendations else 0,
        "recommendation_count": len(recommendations),
        "opportunity_id": None,
    }
