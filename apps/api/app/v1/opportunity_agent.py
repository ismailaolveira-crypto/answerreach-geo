"""Codex-backed, evidence-gated discovery for priority opportunities."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import QueueJob
from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.services.agent_runtime import AgentRuntimeAdapter, get_agent_runtime
from app.v1.action_opportunities import (
    _fingerprint,
    _source_candidates,
    _source_url,
    valid_action_evidence,
)


AGENT_RULE_VERSION = "codex-opportunity.v1"
ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[2]
    / "private_artifacts"
    / "opportunity-discovery"
)
ALLOWED_PLATFORMS = {
    "official_site",
    "zhihu",
    "juejin",
    "csdn",
    "51cto",
    "wechat",
    "xiaohongshu",
}
ALLOWED_STRATEGIES = {
    "direct_operable_source",
    "official_site_handoff",
    "build_controlled_alternative",
}
ALLOWED_TYPES = {"brand_absent", "competitor_gap", "citation_gap"}


DEVELOPER_INSTRUCTIONS = """You are the opportunity analyst for 春秋元泉 GEO.
Analyze only the observation evidence supplied in the prompt. Do not inspect local files, the parent
repository, databases, environment variables, credentials, or browser profiles. Do not publish, submit,
log in, or generate article drafts. Do not invent an opportunity merely to fill the output. A recommendation
must name the exact evidence IDs that justify it. Prefer no action when evidence is weak or contradictory.
Separate official-site developer advice from content that can be drafted for an operable platform. Treat
third-party cited pages as reference material, never as editable property. Return only JSON matching the
supplied schema. For target_source_url, copy one URL byte-for-byte from sources[].url of the listed
evidence_ids, or return an empty string. Never invent, shorten, normalize, or substitute a URL. The
recommended_platforms field is the publishing destination; do not put a platform homepage URL into
target_source_url unless that exact URL appears in the supplied evidence."""


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis_summary": {"type": "string"},
        "opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_plan_id": {"type": "integer"},
                    "opportunity_type": {
                        "type": "string",
                        "enum": sorted(ALLOWED_TYPES),
                    },
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "priority_label": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "priority_score": {"type": "number"},
                    "confidence": {"type": "number"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "recommended_asset_type": {"type": "string"},
                    "recommended_platforms": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": sorted(ALLOWED_PLATFORMS),
                        },
                    },
                    "source_strategy": {
                        "type": "string",
                        "enum": sorted(ALLOWED_STRATEGIES),
                    },
                    "target_source_url": {"type": "string"},
                    "missing_content": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "competitor_content_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rationale": {"type": "string"},
                    "uncertainties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "question_plan_id",
                    "opportunity_type",
                    "title",
                    "summary",
                    "priority_label",
                    "priority_score",
                    "confidence",
                    "evidence_ids",
                    "recommended_asset_type",
                    "recommended_platforms",
                    "source_strategy",
                    "target_source_url",
                    "missing_content",
                    "competitor_content_patterns",
                    "rationale",
                    "uncertainties",
                ],
                "additionalProperties": False,
            },
        },
        "no_action_reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_plan_id": {"type": "integer"},
                    "reason": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["question_plan_id", "reason", "evidence_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["analysis_summary", "opportunities", "no_action_reasons"],
    "additionalProperties": False,
}


def _selected_values(values: Iterable[str] | None) -> list[str]:
    return sorted({str(value).strip() for value in (values or []) if str(value).strip()})


def build_opportunity_context(
    db: Session,
    workspace_id: int,
    *,
    batch_id: int,
    model_keys: Iterable[str] | None = None,
    question_plan_ids: Iterable[int] | None = None,
) -> dict:
    workspace = db.get(GeoWorkspace, workspace_id)
    batch = db.get(GeoObservationBatch, batch_id)
    if workspace is None or batch is None or batch.workspace_id != workspace_id:
        raise ValueError("Observation batch is not available in this workspace")
    if batch.status not in {"completed", "succeeded"}:
        raise ValueError("Only a completed observation batch can be analyzed")

    selected_models = _selected_values(model_keys)
    selected_questions = sorted({int(value) for value in (question_plan_ids or [])})
    task_query = select(GeoObservationTask).where(
        GeoObservationTask.workspace_id == workspace_id,
        GeoObservationTask.batch_id == batch_id,
        GeoObservationTask.status.in_(("completed", "succeeded")),
        GeoObservationTask.evidence_id.is_not(None),
    )
    if selected_models:
        task_query = task_query.where(GeoObservationTask.model_key.in_(selected_models))
    if selected_questions:
        task_query = task_query.where(
            GeoObservationTask.question_plan_id.in_(selected_questions)
        )
    tasks = list(db.scalars(task_query.order_by(GeoObservationTask.id.asc())))
    evidence_ids = [int(task.evidence_id) for task in tasks if task.evidence_id]
    evidence_by_id = {
        row.id: row
        for row in db.scalars(
            select(GeoEvidence).where(
                GeoEvidence.workspace_id == workspace_id,
                GeoEvidence.id.in_(evidence_ids or [-1]),
            )
        )
        if valid_action_evidence(row)
    }
    tasks = [task for task in tasks if int(task.evidence_id or 0) in evidence_by_id]
    if not tasks:
        raise ValueError(
            "The selected scope has no complete real evidence with answer, search event, source URL, and raw artifact"
        )

    question_ids = sorted({task.question_plan_id for task in tasks})
    questions = {
        row.id: row
        for row in db.scalars(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace_id,
                GeoQuestionPlan.id.in_(question_ids),
            )
        )
    }
    rows = []
    for task in tasks:
        evidence = evidence_by_id[int(task.evidence_id or 0)]
        question = questions.get(task.question_plan_id)
        rows.append(
            {
                "evidence_id": evidence.id,
                "question_plan_id": evidence.question_plan_id,
                "question": question.question_text if question else task.question_text_snapshot,
                "question_importance": question.importance if question else 0,
                "model_key": evidence.model_key,
                "model_label": evidence.model_label,
                "brand_status": evidence.brand_status,
                "brand_position": evidence.brand_position,
                "competitors": evidence.competitor_positions or [],
                "answer_excerpt": evidence.answer_text[:5000],
                "sources": [
                    {
                        "url": url,
                        "title": str(source.get("title") or source.get("name") or "")[:240],
                    }
                    for source in (evidence.source_items or [])
                    if isinstance(source, dict) and (url := _source_url(source))
                ],
                "answer_hash": evidence.answer_hash,
                "captured_at": evidence.captured_at.isoformat(),
            }
        )
    scope = {
        "workspace_id": workspace_id,
        "batch_id": batch_id,
        "model_keys": selected_models,
        "question_plan_ids": selected_questions,
    }
    input_fingerprint = sha256(
        json.dumps(
            {
                "scope": scope,
                "evidence": [
                    {"id": row["evidence_id"], "hash": row["answer_hash"]} for row in rows
                ],
                "schema": AGENT_RULE_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "geo-opportunity-analysis.v1",
        "workspace": {
            "id": workspace.id,
            "brand_name": workspace.brand_name,
            "official_website": workspace.website_url,
        },
        "scope": scope,
        "input_fingerprint": input_fingerprint,
        "evidence_gate": "completed_task+real_answer+search_event+source_url+raw_artifact",
        "evidence": rows,
    }


def _prompt(context: dict) -> str:
    return """Analyze the supplied completed GEO observation batch and decide which actions are genuinely
worth doing. An opportunity is not simply a missing brand mention. Compare the cited source patterns,
the content models use when competitors appear, source controllability, and whether a concrete missing
content asset can be produced. Use official_site only for developer advice. Use direct_operable_source
only when the cited domain is a platform we can operate. Use build_controlled_alternative when cited pages
are third-party references and recommend an operable platform instead. target_source_url is evidence
provenance, not the publishing destination: it must be an exact sources[].url value belonging to the
opportunity's evidence_ids, or an empty string. Never construct a Zhihu, Juejin, CSDN, WeChat, 51CTO,
Xiaohongshu, or official-site URL. Return no recommendation when the evidence does not justify one. Do
not draft content.

INPUT_CONTEXT:
""" + json.dumps(context, ensure_ascii=False, indent=2)


def _validate_result(context: dict, parsed: dict) -> list[dict]:
    evidence_by_id = {int(row["evidence_id"]): row for row in context["evidence"]}
    allowed_question_ids = {int(row["question_plan_id"]) for row in context["evidence"]}
    validated: list[dict] = []
    for raw in parsed.get("opportunities") or []:
        question_id = int(raw.get("question_plan_id") or 0)
        if question_id not in allowed_question_ids:
            raise ValueError("Codex returned a question outside the selected scope")
        evidence_ids = list(dict.fromkeys(int(value) for value in raw.get("evidence_ids") or []))
        if not evidence_ids:
            raise ValueError("Codex opportunity has no evidence IDs")
        if any(value not in evidence_by_id for value in evidence_ids):
            raise ValueError("Codex returned evidence outside the selected scope")
        if any(
            int(evidence_by_id[value]["question_plan_id"]) != question_id
            for value in evidence_ids
        ):
            raise ValueError("Codex mixed evidence from different questions")
        target_url = str(raw.get("target_source_url") or "").strip()
        observed_urls = {
            str(source.get("url") or "")
            for value in evidence_ids
            for source in evidence_by_id[value].get("sources") or []
        }
        if target_url and target_url not in observed_urls:
            raise ValueError("Codex returned a target source URL that was not observed")
        platforms = list(dict.fromkeys(str(value) for value in raw.get("recommended_platforms") or []))
        if not platforms or any(value not in ALLOWED_PLATFORMS for value in platforms):
            raise ValueError("Codex opportunity has invalid target platforms")
        strategy = str(raw.get("source_strategy") or "")
        if strategy not in ALLOWED_STRATEGIES:
            raise ValueError("Codex opportunity has an invalid source strategy")
        if strategy in {"direct_operable_source", "official_site_handoff"} and not target_url:
            raise ValueError("Codex opportunity is missing its observed target source URL")
        opportunity_type = str(raw.get("opportunity_type") or "")
        if opportunity_type not in ALLOWED_TYPES:
            raise ValueError("Codex opportunity has an invalid type")
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        rationale = str(raw.get("rationale") or "").strip()
        if not title or not summary or not rationale:
            raise ValueError("Codex opportunity is missing its decision explanation")
        confidence = float(raw.get("confidence") or 0)
        priority_score = float(raw.get("priority_score") or 0)
        if not 0 <= confidence <= 1 or not 0 <= priority_score <= 100:
            raise ValueError("Codex opportunity scores are outside their valid range")
        validated.append(
            {
                **raw,
                "question_plan_id": question_id,
                "evidence_ids": evidence_ids,
                "recommended_platforms": platforms,
                "source_strategy": strategy,
                "opportunity_type": opportunity_type,
                "title": title[:255],
                "summary": summary,
                "rationale": rationale,
                "target_source_url": target_url,
                "confidence": confidence,
                "priority_score": priority_score,
            }
        )
    return validated


def materialize_agent_opportunities(
    db: Session,
    *,
    job: QueueJob,
    context: dict,
    parsed: dict,
) -> list[GeoActionOpportunity]:
    workspace = db.get(GeoWorkspace, int(context["workspace"]["id"]))
    if workspace is None:
        raise ValueError("Workspace disappeared during opportunity analysis")
    validated = _validate_result(context, parsed)
    evidence_by_id = {
        row.id: row
        for row in db.scalars(
            select(GeoEvidence).where(
                GeoEvidence.workspace_id == workspace.id,
                GeoEvidence.id.in_(
                    [value for item in validated for value in item["evidence_ids"]] or [-1]
                ),
            )
        )
    }
    task_by_evidence = {
        int(task.evidence_id): task
        for task in db.scalars(
            select(GeoObservationTask).where(
                GeoObservationTask.workspace_id == workspace.id,
                GeoObservationTask.batch_id == int(context["scope"]["batch_id"]),
                GeoObservationTask.evidence_id.in_(list(evidence_by_id) or [-1]),
            )
        )
        if task.evidence_id
    }
    for existing in db.scalars(
        select(GeoActionOpportunity).where(
            GeoActionOpportunity.workspace_id == workspace.id,
            GeoActionOpportunity.rule_version == AGENT_RULE_VERSION,
            GeoActionOpportunity.status == "open",
        )
    ):
        if (existing.scope_snapshot or {}).get("input_fingerprint") == context["input_fingerprint"]:
            existing.status = "stale"

    materialized: list[GeoActionOpportunity] = []
    for item in validated:
        evidence_rows = [evidence_by_id[value] for value in item["evidence_ids"]]
        source_candidates = _source_candidates(
            evidence_rows,
            official_website=workspace.website_url,
        )
        target_url = item["target_source_url"]
        primary_source = next(
            (source for source in source_candidates if source.get("url") == target_url),
            None,
        )
        if (
            item["source_strategy"] == "direct_operable_source"
            and (primary_source or {}).get("controllability") != "operable_platform"
        ):
            raise ValueError("Codex marked a non-operable source as directly operable")
        if (
            item["source_strategy"] == "official_site_handoff"
            and (primary_source or {}).get("controllability") != "owned"
        ):
            raise ValueError("Codex website handoff does not target the owned website")
        context_evidence = next(
            row
            for row in context["evidence"]
            if int(row["question_plan_id"]) == item["question_plan_id"]
        )
        fingerprint = _fingerprint(
            workspace.id,
            context["input_fingerprint"],
            item["question_plan_id"],
            item["opportunity_type"],
            target_url or item["source_strategy"],
            AGENT_RULE_VERSION,
        )
        opportunity = db.scalar(
            select(GeoActionOpportunity).where(
                GeoActionOpportunity.workspace_id == workspace.id,
                GeoActionOpportunity.fingerprint == fingerprint,
            )
        )
        snapshot = {
            **context["scope"],
            "source_type": "model_observation",
            "question_plan_id": item["question_plan_id"],
            "question": context_evidence["question"],
            "input_fingerprint": context["input_fingerprint"],
            "discovery_job_id": job.id,
            "codex_thread_id": (job.payload_json or {}).get("codex_thread_id"),
            "codex_turn_id": (job.payload_json or {}).get("codex_turn_id"),
            "agent_confidence": item["confidence"],
            "agent_rationale": item["rationale"],
            "missing_content": list(item.get("missing_content") or []),
            "competitor_content_patterns": list(
                item.get("competitor_content_patterns") or []
            ),
            "uncertainties": list(item.get("uncertainties") or []),
            "source_candidates": source_candidates,
            "source_strategy": item["source_strategy"],
            "primary_source": primary_source,
            "recommended_carrier": item["recommended_asset_type"],
            "eligibility": context["evidence_gate"],
        }
        values = {
            "opportunity_type": item["opportunity_type"],
            "title": item["title"],
            "summary": item["summary"],
            "priority_score": round(item["priority_score"], 2),
            "priority_label": item["priority_label"],
            "evidence_strength": round(item["confidence"], 4),
            "source_gap_type": "agent_identified_content_gap",
            "recommended_asset_type": item["recommended_asset_type"][:40],
            "recommended_platforms": item["recommended_platforms"],
            "scope_snapshot": snapshot,
            "rule_version": AGENT_RULE_VERSION,
            "latest_seen_batch_id": int(context["scope"]["batch_id"]),
        }
        if opportunity is None:
            opportunity = GeoActionOpportunity(
                workspace_id=workspace.id,
                fingerprint=fingerprint,
                status="open",
                first_seen_batch_id=int(context["scope"]["batch_id"]),
                **values,
            )
            db.add(opportunity)
            db.flush()
        elif opportunity.status not in {"selected", "completed", "dismissed"}:
            for key, value in values.items():
                setattr(opportunity, key, value)
            opportunity.status = "open"
        for evidence in evidence_rows:
            task = task_by_evidence.get(evidence.id)
            link = db.scalar(
                select(GeoActionOpportunityEvidence).where(
                    GeoActionOpportunityEvidence.opportunity_id == opportunity.id,
                    GeoActionOpportunityEvidence.evidence_id == evidence.id,
                )
            )
            if link is not None:
                continue
            first_source = next(
                (
                    _source_url(source)
                    for source in (evidence.source_items or [])
                    if _source_url(source)
                ),
                None,
            )
            db.add(
                GeoActionOpportunityEvidence(
                    opportunity_id=opportunity.id,
                    workspace_id=workspace.id,
                    batch_id=task.batch_id if task else int(context["scope"]["batch_id"]),
                    observation_task_id=task.id if task else None,
                    evidence_id=evidence.id,
                    question_plan_id=evidence.question_plan_id,
                    provider_id=task.provider_id if task else None,
                    model_key=evidence.model_key,
                    signal_type=item["opportunity_type"],
                    signal_value={
                        "brand_status": evidence.brand_status,
                        "agent_confidence": item["confidence"],
                        "discovery_job_id": job.id,
                    },
                    evidence_hash=evidence.answer_hash,
                    source_url=first_source,
                )
            )
        materialized.append(opportunity)
    db.flush()
    return sorted(materialized, key=lambda row: (-row.priority_score, row.id))


def execute_opportunity_analysis(
    db: Session,
    job: QueueJob,
    *,
    runtime: AgentRuntimeAdapter | None = None,
) -> dict:
    payload = dict(job.payload_json or {})
    context = build_opportunity_context(
        db,
        int(payload["workspace_id"]),
        batch_id=int(payload["batch_id"]),
        model_keys=payload.get("model_keys") or [],
        question_plan_ids=payload.get("question_plan_ids") or [],
    )
    if payload.get("input_fingerprint") != context["input_fingerprint"]:
        raise ValueError("Observation evidence changed before Codex analysis began; start a new run")
    task_directory = ARTIFACT_ROOT / str(payload["workspace_id"]) / str(job.id)
    task_directory.mkdir(parents=True, exist_ok=True)
    context_path = task_directory / "input.json"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {**payload, "stage": "analyzing", "evidence_count": len(context["evidence"])}
    job.payload_json = payload
    db.add(job)
    db.commit()

    runtime_key = str(payload.get("runtime_key") or "local_codex")
    runtime = runtime or get_agent_runtime(runtime_key)

    def on_started(thread_id: str, turn_id: str) -> None:
        current = dict(job.payload_json or {})
        job.payload_json = {
            **current,
            "stage": "analyzing",
            "agent_session_id": thread_id,
            "agent_turn_id": turn_id,
            **({"codex_thread_id": thread_id, "codex_turn_id": turn_id} if runtime_key == "local_codex" else {}),
        }
        db.add(job)
        db.commit()

    result = runtime.run_structured(
        task_directory=task_directory,
        prompt=_prompt(context),
        output_schema=OUTPUT_SCHEMA,
        developer_instructions=DEVELOPER_INSTRUCTIONS,
        model=payload.get("model"),
        reasoning_effort=payload.get("reasoning_effort"),
        on_started=on_started,
        timeout_seconds=max(60, min(int(get_settings().agent_run_timeout_seconds), 3600)),
    )
    parsed = json.loads(result.final_response)
    result_path = task_directory / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "result": parsed,
                "usage": result.usage,
                "runtime_key": runtime_key,
                "agent_session_id": result.thread_id,
                "agent_turn_id": result.turn_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    opportunities = materialize_agent_opportunities(
        db,
        job=job,
        context=context,
        parsed=parsed,
    )
    job.payload_json = {
        **dict(job.payload_json or {}),
        "stage": "complete",
        "result_count": len(opportunities),
        "analysis_summary": str(parsed.get("analysis_summary") or "")[:1000],
        "no_action_count": len(parsed.get("no_action_reasons") or []),
        "agent_session_id": result.thread_id,
        "agent_turn_id": result.turn_id,
        **({"codex_thread_id": result.thread_id, "codex_turn_id": result.turn_id} if runtime_key == "local_codex" else {}),
        "result_sha256": sha256(result_path.read_bytes()).hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add(job)
    db.commit()
    return {
        "stage": "complete",
        "result_count": len(opportunities),
        "opportunity_ids": [row.id for row in opportunities],
    }
