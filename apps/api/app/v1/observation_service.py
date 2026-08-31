import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, LLMProvider, Project
from app.models.cleanroom_v1 import (
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoScorecard,
)
from app.models.user import User
from app.services.llm_provider import get_search_provider
from app.services.usage import enforce_monthly_search_budget, record_usage
from app.services.workspace_access import require_workspace_access
from app.services.workspace_secrets import DEEPSEEK_API_KEY, get_workspace_secret
from app.v1.evidence_analysis import analyze_brand_status
from app.v1.schemas import OfficialApiObservationRequest
from app.v1.scoring import SCORING_VERSION, score_evidence


API_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_API_ARTIFACT_ROOT = API_ROOT / "private_artifacts" / "official_api"

SEARCH_PROVIDER_TYPES = {
    "deepseek_web_search",
    "kimi_web_search",
    "hunyuan_web_search",
    "qwen_compatible",
    "bailian_qwen_responses",
    "volcengine_ark",
    "xiaoma_domestic_web_search",
}

MODEL_LABELS = {
    "deepseek": "DeepSeek",
    "doubao": "豆包",
    "kimi": "Kimi",
    "glm": "智谱 GLM",
    "qianwen": "通义千问",
    "yuanbao": "腾讯元宝",
    "hunyuan": "腾讯混元",
}

STANDARD_MODELS = (
    ("deepseek", "DeepSeek"),
    ("doubao", "豆包"),
    ("qianwen", "通义千问"),
    ("glm", "智谱 GLM"),
    ("kimi", "Kimi"),
    ("hunyuan", "腾讯混元"),
)


def provider_model_key(provider: LLMProvider) -> str:
    configured_key = str((provider.cost_rule or {}).get("platform_key") or "").strip().lower()
    aliases = {
        "qwen": "qianwen",
        "qianwen": "qianwen",
        "deepseek": "deepseek",
        "doubao": "doubao",
        "kimi": "kimi",
        "glm": "glm",
        "hunyuan": "hunyuan",
    }
    if configured_key in aliases:
        return aliases[configured_key]
    value = f"{provider.name} {provider.provider_type} {provider.model_name}".lower()
    if "doubao" in value or "豆包" in value:
        return "doubao"
    if "kimi" in value or "moonshot" in value:
        return "kimi"
    if "glm" in value or "智谱" in value or "zhipu" in value:
        return "glm"
    if "qwen" in value or "千问" in value or "dashscope" in value:
        return "qianwen"
    if "hunyuan" in value or "混元" in value:
        return "hunyuan"
    return "deepseek"


def provider_model_label(provider: LLMProvider, model_key: str) -> str:
    labels = {
        "deepseek": "DeepSeek",
        "doubao": "豆包",
        "qianwen": "通义千问",
        "kimi": "Kimi",
        "glm": "智谱 GLM",
        "hunyuan": "腾讯混元",
    }
    label = labels.get(model_key, provider.name)
    transport = "聚合 API" if provider.provider_type == "xiaoma_domestic_web_search" else "官方 API"
    return f"{label} · {transport} + 联网搜索"


def question_sampling_eligible(plan: GeoQuestionPlan) -> bool:
    return plan.active and plan.status in {"approved", "active"} and not plan.is_brand_query


def write_scorecard(db: Session, workspace_id: int, run_id: int) -> GeoScorecard:
    evidence = list(
        db.scalars(
            select(GeoEvidence).where(
                GeoEvidence.workspace_id == workspace_id, GeoEvidence.run_id == run_id
            )
        )
    )
    metrics, explanation, fingerprint = score_evidence(evidence)
    scorecard = GeoScorecard(
        workspace_id=workspace_id,
        run_id=run_id,
        scoring_version=SCORING_VERSION,
        input_fingerprint=fingerprint,
        metrics=metrics,
        explanation=explanation,
    )
    db.add(scorecard)
    db.flush()
    return scorecard


def refresh_observation_ledger_batch(db: Session, batch_id: int) -> None:
    """Derive batch progress from persisted task rows, never from UI state."""

    batch = db.get(GeoObservationBatch, batch_id)
    if batch is None:
        return
    completed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .where(
                GeoObservationTask.batch_id == batch_id,
                GeoObservationTask.status == "completed",
            )
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .where(
                GeoObservationTask.batch_id == batch_id,
                GeoObservationTask.status == "failed",
            )
        )
        or 0
    )
    running = int(
        db.scalar(
            select(func.count())
            .select_from(GeoObservationTask)
            .where(
                GeoObservationTask.batch_id == batch_id,
                GeoObservationTask.status == "running",
            )
        )
        or 0
    )
    batch.completed_tasks = completed
    batch.failed_tasks = failed
    if completed + failed >= batch.total_tasks and batch.total_tasks > 0:
        batch.status = "completed" if failed == 0 else "partial"
        batch.completed_at = batch.completed_at or datetime.now(timezone.utc)
    elif completed or failed or running:
        batch.status = "running"
        batch.started_at = batch.started_at or datetime.now(timezone.utc)
        batch.completed_at = None
    else:
        batch.status = "pending"
        batch.completed_at = None
    db.add(batch)


def collect_provider_web_search(
    db: Session,
    *,
    workspace_id: int,
    payload: OfficialApiObservationRequest,
    user: User,
    observation_task_id: int | None = None,
) -> dict:
    """Collect and persist one auditable Provider search observation."""

    workspace, _membership = require_workspace_access(db, user, workspace_id)
    question = db.get(GeoQuestionPlan, payload.question_plan_id)
    if question is None or question.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    if not question_sampling_eligible(question):
        raise HTTPException(status_code=409, detail="问题尚未人工批准，不能进入正式采样")
    if payload.provider_id is not None:
        provider = db.get(LLMProvider, payload.provider_id)
        if (
            provider is None
            or provider.status != "active"
            or provider.provider_type not in SEARCH_PROVIDER_TYPES
        ):
            raise HTTPException(
                status_code=422, detail="所选模型未启用，或不具备可审计的联网搜索能力"
            )
    else:
        provider = db.scalar(
            select(LLMProvider)
            .where(
                LLMProvider.provider_type == "deepseek_web_search", LLMProvider.status == "active"
            )
            .order_by(LLMProvider.id.desc())
        )
    if provider is None:
        raise HTTPException(status_code=422, detail="请先在运营设置中配置并测试一个联网模型")
    try:
        budget = enforce_monthly_search_budget(db, provider, projected_calls=1)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    model_key = provider_model_key(provider)
    model_label = provider_model_label(provider, model_key)
    prompt_text = question.question_text

    task_id = int(observation_task_id or 0)
    observation_task = db.get(GeoObservationTask, task_id) if task_id else None
    if task_id and observation_task is None:
        raise HTTPException(status_code=404, detail="观测任务不存在")
    if observation_task is not None and (
        observation_task.workspace_id != workspace_id
        or observation_task.provider_id != provider.id
        or observation_task.question_plan_id != question.id
        or observation_task.repeat_index != payload.repeat_index
    ):
        raise HTTPException(status_code=409, detail="观测任务与模型或问题不匹配")
    if observation_task is None:
        ledger_batch = GeoObservationBatch(
            workspace_id=workspace_id,
            requested_by_user_id=user.id,
            source_type="official_api_direct",
            status="pending",
            provider_count=1,
            question_count=1,
            repeat_count=payload.repeat_count,
            total_tasks=1,
            configuration={
                "schema": "unified-observation-ledger/v1",
                "providers": [{"id": provider.id, "key": model_key, "label": model_label}],
                "questions": [
                    {"id": question.id, "key": str(question.id), "label": question.question_text}
                ],
            },
        )
        db.add(ledger_batch)
        db.flush()
        observation_task = GeoObservationTask(
            batch_id=ledger_batch.id,
            workspace_id=workspace_id,
            provider_id=provider.id,
            provider_key=provider.provider_type,
            provider_label=model_label,
            model_key=model_key,
            model_label=model_label,
            question_plan_id=question.id,
            question_text_snapshot=question.question_text,
            sample_key=f"provider:{provider.id}:question:{question.id}:repeat:{payload.repeat_index}",
            repeat_index=payload.repeat_index,
            repeat_count=payload.repeat_count,
            observation_group_id=payload.observation_group_id,
            status="pending",
        )
        db.add(observation_task)
        db.flush()
        task_id = observation_task.id

    started_at = datetime.now(timezone.utc)
    run = GeoObservationRun(
        workspace_id=workspace_id,
        adapter_key="provider-web-search/v1",
        status="running",
        request_context={
            "schema": "spring-yuan-official-api-observation/v1",
            "provider_id": provider.id,
            "provider_type": provider.provider_type,
            "model": provider.model_name,
            "question_plan_id": question.id,
            "prompt_version": question.prompt_version,
            "repeat_index": payload.repeat_index,
            "repeat_count": payload.repeat_count,
            "observation_group_id": payload.observation_group_id,
            "transport": "aggregate_responses_api"
            if provider.provider_type == "xiaoma_domestic_web_search"
            else "provider_api",
            "model_key": model_key,
            "search_required": True,
        },
        started_at=started_at,
    )
    db.add(run)
    db.flush()
    observation_task.run_id = run.id
    observation_task.status = "running"
    observation_task.attempt_count = max(1, observation_task.attempt_count)
    observation_task.started_at = observation_task.started_at or started_at
    observation_task.error_code = None
    observation_task.error_detail = None
    refresh_observation_ledger_batch(db, observation_task.batch_id)
    db.commit()
    db.refresh(run)

    company = db.get(Company, workspace.company_id) or Company(
        name=workspace.brand_name,
        industry="",
        website_url=workspace.website_url,
        brand_aliases=workspace.brand_aliases,
    )
    project = Project(
        company_id=workspace.company_id,
        name=f"{workspace.brand_name} GEO provider observation",
        target_industry=company.industry,
        target_audience="企业采购决策者",
    )
    try:
        workspace_api_key = (
            get_workspace_secret(db, workspace_id, DEEPSEEK_API_KEY)
            if provider.provider_type == "deepseek_web_search"
            else None
        )
        answer = get_search_provider(provider, api_key_override=workspace_api_key).answer(
            prompt_text, company, project, []
        )
        if answer.collection_method not in {"official_api_web_search", "aggregate_api_web_search"}:
            raise ValueError("Provider did not return eligible API web-search evidence")
        if not answer.search_verified or answer.search_event_count < 1:
            raise ValueError("Provider response did not pass the Web Search execution gate")
        if not answer.source_items or not answer.raw_provider_payload:
            raise ValueError("Provider response is missing searchable source artifacts")

        captured_at = datetime.now(timezone.utc)
        sample_dir = OFFICIAL_API_ARTIFACT_ROOT / model_key / f"run-{run.id}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = sample_dir / "response.json"
        artifact_payload = {
            "schema_version": "spring-yuan-provider-web-search/v1",
            "run_id": run.id,
            "provider_id": provider.id,
            "provider_type": provider.provider_type,
            "model": provider.model_name,
            "question_plan_id": question.id,
            "question": question.question_text,
            "answer": answer.raw_answer,
            "sources": answer.source_items,
            "search_verification": answer.search_verification,
            "captured_at": captured_at.isoformat(),
            "raw_provider_response": answer.raw_provider_payload,
        }
        temporary_path = artifact_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(artifact_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(artifact_path)
        if not artifact_path.exists() or artifact_path.stat().st_size == 0:
            raise ValueError("Provider raw response archive was not created")

        owned_domains: list[str] = []
        website_host = urlsplit(workspace.website_url or "").hostname
        if website_host:
            owned_domains.append(website_host)
        brand_status, brand_position = analyze_brand_status(
            answer.raw_answer,
            answer.source_items,
            workspace.brand_name,
            workspace.brand_aliases,
            owned_domains,
        )
        answer_hash = sha256(
            f"{run.id}|{question.id}|{answer.raw_answer.strip()}".encode()
        ).hexdigest()
        evidence = GeoEvidence(
            workspace_id=workspace_id,
            run_id=run.id,
            question_plan_id=question.id,
            model_key=model_key,
            model_label=model_label,
            prompt_version=question.prompt_version,
            sample_mode="authorized_api",
            evidence_level="auditable",
            collection_method=answer.collection_method,
            evidence_kind="provider_web_search",
            is_real_provider_evidence=True,
            brand_status=brand_status,
            brand_position=brand_position,
            competitor_positions=[],
            answer_text=answer.raw_answer.strip(),
            answer_hash=answer_hash,
            source_items=answer.source_items,
            sampling_environment={
                "observation_surface": "official_api",
                "web_ui_equivalence": "not_claimed",
                "provider_id": provider.id,
                "provider_type": provider.provider_type,
                "model": provider.model_name,
                "thinking_mode": str(provider.cost_rule.get("thinking_type") or "disabled"),
                "reasoning_effort": str(provider.cost_rule.get("reasoning_effort") or "low"),
                "endpoint_family": {
                    "deepseek_web_search": "anthropic_messages",
                    "kimi_web_search": "openai_chat_completions_plus_formula",
                    "hunyuan_web_search": "tokenhub_responses",
                }.get(provider.provider_type, "responses_api"),
                "search_required": True,
                "search_verified": answer.search_verified,
                "search_event_count": answer.search_event_count,
                "search_gate": answer.search_verification.get("gate"),
                "search_protocol": answer.search_verification.get("protocol"),
                "official_search_tool": answer.search_verification.get("official_tool")
                or answer.search_verification.get("formula_uri"),
                "search_source_count": len(answer.source_items),
                "repeat_index": payload.repeat_index,
                "repeat_count": payload.repeat_count,
                "observation_group_id": payload.observation_group_id,
                "prompt_is_exact_question": True,
                "personalization": "none",
                "screenshot_applicable": False,
            },
            raw_artifact_uri=artifact_path.resolve().as_uri(),
            screenshot_uri=None,
            captured_at=captured_at,
        )
        db.add(evidence)
        run.status = "completed"
        run.completed_at = captured_at
        run.request_context = {
            **run.request_context,
            "evidence_protocol": "answer+search_sources+raw_provider_response",
            "search_source_count": len(answer.source_items),
        }
        db.flush()
        observation_task = db.get(GeoObservationTask, task_id)
        if observation_task is not None:
            observation_task.run_id = run.id
            observation_task.evidence_id = evidence.id
            observation_task.status = "completed"
            observation_task.completed_at = captured_at
            observation_task.error_code = None
            observation_task.error_detail = None
            refresh_observation_ledger_batch(db, observation_task.batch_id)
        record_usage(
            db,
            provider=provider,
            action="crawl.answer",
            prompt_text=prompt_text,
            completion_text=answer.raw_answer,
            company_id=workspace.company_id,
            detail={
                "source": "cleanroom_official_api_observation",
                "run_id": run.id,
                "search_event_count": answer.search_event_count,
                "monthly_budget": budget,
            },
        )
        scorecard = write_scorecard(db, workspace_id, run.id)
        db.commit()
        db.refresh(run)
        db.refresh(evidence)
        db.refresh(scorecard)
        return {
            "run": run,
            "evidence": evidence,
            "scorecard": scorecard,
            "message": f"{model_label} 回答、搜索来源和原始响应已归档。",
        }
    except Exception as exc:
        db.rollback()
        failed_run = db.get(GeoObservationRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at = datetime.now(timezone.utc)
            failed_run.failure_reason = str(exc)[:2000]
            record_usage(
                db,
                provider=provider,
                action="crawl.answer",
                prompt_text=prompt_text,
                completion_text="",
                company_id=workspace.company_id,
                detail={
                    "source": "cleanroom_official_api_observation",
                    "run_id": run.id,
                    "ok": False,
                    "error": str(exc)[:800],
                },
            )
            observation_task = db.get(GeoObservationTask, task_id)
            if observation_task is not None:
                observation_task.run_id = run.id
                observation_task.status = "failed"
                observation_task.error_code = type(exc).__name__[:80]
                observation_task.error_detail = str(exc)[:2000]
                observation_task.completed_at = failed_run.completed_at
                refresh_observation_ledger_batch(db, observation_task.batch_id)
            db.commit()
        raise HTTPException(
            status_code=502, detail=f"模型联网搜索观测失败：{str(exc)[:800]}"
        ) from exc
