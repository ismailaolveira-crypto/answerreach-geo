from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Competitor,
    CrawlResult,
    CrawlTask,
    CrawlTaskLog,
    Keyword,
    LLMProvider,
    LLMProviderTestRun,
    Project,
    TargetQuestion,
)
from app.schemas.search import CrawlTaskCreate, CrawlTaskEstimateProvider, CrawlTaskEstimateRead
from app.services.answer_parser import analyze_answer
from app.services.llm_provider import diagnose_provider, get_search_provider
from app.services.usage import enforce_monthly_search_budget, estimate_cost, estimate_tokens, record_usage


KEYWORD_PROMPT_VARIANT_COUNT = 3
ESTIMATED_COMPLETION_TOKENS_PER_CALL = 900


def build_keyword_prompt_variants(keyword: str, industry: str | None = None) -> list[str]:
    keyword_text = keyword.strip()
    industry_text = (industry or "").strip()
    context = f"{industry_text}领域" if industry_text else "企业服务领域"
    return [
        f"{keyword_text}相关服务商怎么选？",
        f"{context}里，{keyword_text}有哪些值得关注的解决方案或服务商？",
        f"企业在采购{keyword_text}服务时，应该重点比较哪些能力和案例？",
    ]


def _default_real_provider_ids(db: Session) -> list[int]:
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.status == "active")
            .where(LLMProvider.provider_type.not_in(["mock", "browser_observation"]))
            .order_by(LLMProvider.id.asc())
        )
    )
    provider_ids: list[int] = []
    for provider in providers:
        latest_test = db.scalar(
            select(LLMProviderTestRun)
            .where(LLMProviderTestRun.provider_id == provider.id)
            .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
            .limit(1)
        )
        if latest_test is not None and latest_test.ok is True:
            provider_ids.append(provider.id)
    return provider_ids


def _log(db: Session, task: CrawlTask, level: str, message: str, detail: dict | None = None) -> None:
    db.add(
        CrawlTaskLog(
            task_id=task.id,
            project_id=task.project_id,
            level=level,
            message=message,
            detail_json=detail or {},
        )
    )
    db.flush()


def _provider_blockers(db: Session, provider_ids: list[int], providers: list[LLMProvider]) -> list[str]:
    providers_by_id = {provider.id: provider for provider in providers}
    blockers: list[str] = []
    for provider_id in provider_ids:
        provider = providers_by_id.get(provider_id)
        if provider is None:
            blockers.append(f"Provider #{provider_id} 不存在或不可用。")
            continue
        if provider.status != "active":
            blockers.append(f"{provider.name} 当前不是 active 状态。")
            continue
        diagnostic = diagnose_provider(provider)
        if not diagnostic["ready"]:
            missing = "、".join(diagnostic["missing"]) or "必要配置"
            blockers.append(f"{provider.name} 缺少 {missing}。")
            continue
        # Mock is an explicitly labeled local/demo execution mode. It is not
        # eligible for real-provider readiness metrics, but it does not need a
        # network test call before the deterministic local runner can execute.
        if provider.provider_type == "mock":
            continue
        latest_test = db.scalar(
            select(LLMProviderTestRun)
            .where(LLMProviderTestRun.provider_id == provider.id)
            .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
            .limit(1)
        )
        if latest_test is None:
            blockers.append(f"{provider.name} 还没有测试记录，请先在模型渠道页完成测试调用。")
        elif latest_test.ok is not True:
            blockers.append(f"{provider.name} 最近一次测试失败：{latest_test.error_message or '未知错误'}。")
    return blockers


def _resolve_provider_ids(db: Session, provider_ids: list[int]) -> list[int]:
    if not provider_ids:
        return _default_real_provider_ids(db)
    return provider_ids


def _resolve_crawl_scope(
    db: Session,
    project: Project,
    *,
    target_question_ids: list[int],
    keyword_ids: list[int],
) -> tuple[list[TargetQuestion], list[Keyword], str]:
    has_explicit_scope = bool(target_question_ids or keyword_ids)
    question_stmt = select(TargetQuestion).where(TargetQuestion.project_id == project.id)
    keyword_stmt = select(Keyword).where(Keyword.project_id == project.id)
    if has_explicit_scope and not target_question_ids:
        questions = []
    elif target_question_ids:
        question_stmt = question_stmt.where(TargetQuestion.id.in_(target_question_ids))
        questions = list(db.scalars(question_stmt))
    else:
        questions = list(db.scalars(question_stmt))

    if has_explicit_scope and not keyword_ids:
        keywords = []
    elif keyword_ids:
        keyword_stmt = keyword_stmt.where(Keyword.id.in_(keyword_ids))
        keywords = list(db.scalars(keyword_stmt))
    else:
        keywords = list(db.scalars(keyword_stmt))

    scope_mode = "selected" if has_explicit_scope else "all_project_inputs"
    return questions, keywords, scope_mode


def estimate_crawl_task(db: Session, project: Project, payload: CrawlTaskCreate) -> CrawlTaskEstimateRead:
    provider_ids = _resolve_provider_ids(db, payload.provider_ids)
    questions, keywords, scope_mode = _resolve_crawl_scope(
        db,
        project,
        target_question_ids=payload.target_question_ids,
        keyword_ids=payload.keyword_ids,
    )
    providers = list(db.scalars(select(LLMProvider).where(LLMProvider.id.in_(provider_ids))))
    blockers = _provider_blockers(db, provider_ids, providers)
    if not providers:
        blockers.append("没有可用的 active 真实 Provider，请先配置并选择模型渠道。")
    prompts: list[str] = [question.question_text for question in questions]
    for keyword in keywords:
        prompts.extend(build_keyword_prompt_variants(keyword.keyword, project.target_industry))
    run_count = payload.sample_runs_per_prompt
    estimated_prompt_tokens = sum(estimate_tokens(prompt) for prompt in prompts) * len(providers) * run_count
    estimated_completion_tokens = len(prompts) * len(providers) * run_count * ESTIMATED_COMPLETION_TOKENS_PER_CALL
    estimated_cost_total = 0.0
    currency = "USD"
    cost_configured_provider_count = 0
    unconfigured_real_provider_count = 0
    provider_items: list[CrawlTaskEstimateProvider] = []
    for provider in providers:
        diagnostic = diagnose_provider(provider)
        provider_prompt_tokens = sum(estimate_tokens(prompt) for prompt in prompts) * run_count
        provider_completion_tokens = len(prompts) * run_count * ESTIMATED_COMPLETION_TOKENS_PER_CALL
        provider_estimated_cost, provider_currency = estimate_cost(
            provider, provider_prompt_tokens, provider_completion_tokens
        )
        provider_cost_rule = provider.cost_rule or {}
        provider_cost_configured = bool(
            float(provider_cost_rule.get("input_per_1k", 0) or 0)
            or float(provider_cost_rule.get("output_per_1k", 0) or 0)
        )
        if provider_cost_configured:
            cost_configured_provider_count += 1
        if provider.provider_type != "mock" and not provider_cost_configured:
            unconfigured_real_provider_count += 1
        estimated_cost_total += provider_estimated_cost
        if provider_currency:
            currency = provider_currency
        provider_items.append(
            CrawlTaskEstimateProvider(
                id=provider.id,
                name=provider.name,
                provider_type=provider.provider_type,
                is_real=provider.provider_type != "mock",
                collection_ready=provider.provider_type == "mock" or diagnostic["ready"],
                cost_configured=provider_cost_configured,
                estimated_cost=provider_estimated_cost,
                currency=provider_currency,
            )
        )

    prompt_count = len(prompts)
    real_provider_count = sum(1 for provider in providers if provider.provider_type != "mock")
    warnings: list[str] = []
    if scope_mode == "all_project_inputs" and prompt_count > 0:
        warnings.append("未选择问题或关键词时会跑完整项目范围。")
    missing_question_count = max(0, len(payload.target_question_ids) - len(questions))
    missing_keyword_count = max(0, len(payload.keyword_ids) - len(keywords))
    if missing_question_count:
        warnings.append(f"{missing_question_count} 个目标问题不属于该项目或已不存在。")
    if missing_keyword_count:
        warnings.append(f"{missing_keyword_count} 个关键词不属于该项目或已不存在。")
    if real_provider_count > 0:
        warnings.append("已选择真实模型渠道，运行后会产生实际 API 调用与费用。")
        if unconfigured_real_provider_count > 0:
            warnings.append("部分真实模型渠道未配置输入/输出单价，预计成本可能被低估。")
    if prompt_count * len(providers) * run_count >= 20:
        warnings.append("本次调用量较高，建议先抽样验证再全量采集。")

    return CrawlTaskEstimateRead(
        provider_count=len(providers),
        real_provider_count=real_provider_count,
        target_question_count=len(questions),
        keyword_count=len(keywords),
        prompt_count=prompt_count,
        total_call_count=prompt_count * len(providers) * run_count,
        estimated_prompt_tokens=estimated_prompt_tokens,
        estimated_completion_tokens=estimated_completion_tokens,
        estimated_total_tokens=estimated_prompt_tokens + estimated_completion_tokens,
        estimated_cost=round(estimated_cost_total, 6),
        currency=currency,
        cost_configured_provider_count=cost_configured_provider_count,
        scope_mode=scope_mode,
        providers=provider_items,
        blockers=blockers,
        warnings=warnings,
    )


def create_crawl_task(db: Session, project: Project, payload: CrawlTaskCreate) -> CrawlTask:
    provider_ids = _resolve_provider_ids(db, payload.provider_ids)

    task = CrawlTask(
        project_id=project.id,
        task_type=payload.task_type,
        schedule_type=payload.schedule_type,
        provider_ids=provider_ids,
        target_question_ids=payload.target_question_ids,
        keyword_ids=payload.keyword_ids,
        sample_runs_per_prompt=payload.sample_runs_per_prompt,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if payload.execute_now and payload.max_estimated_cost is not None and not payload.allow_over_budget:
        estimate = estimate_crawl_task(db, project, payload)
        if estimate.real_provider_count > 0 and estimate.estimated_cost > payload.max_estimated_cost:
            task.status = "failed"
            task.finished_at = datetime.now(UTC)
            task.error_message = (
                "Budget guard blocked crawl: "
                f"estimated_cost={estimate.estimated_cost} {estimate.currency}, "
                f"max_estimated_cost={payload.max_estimated_cost} {estimate.currency}."
            )
            _log(
                db,
                task,
                "warning",
                "Crawl blocked by budget guard",
                {
                    "estimated_cost": estimate.estimated_cost,
                    "max_estimated_cost": payload.max_estimated_cost,
                    "currency": estimate.currency,
                    "estimated_total_tokens": estimate.estimated_total_tokens,
                    "total_call_count": estimate.total_call_count,
                },
            )
            db.commit()
            db.refresh(task)
            return task
    if payload.execute_now:
        run_crawl_task(db, task, payload)
    return task


def run_crawl_task(db: Session, task: CrawlTask, payload: CrawlTaskCreate | None = None) -> CrawlTask:
    project = db.get(Project, task.project_id)
    if project is None:
        task.status = "failed"
        task.error_message = "Project not found"
        db.commit()
        return task

    company = db.get(Company, project.company_id)
    if company is None:
        task.status = "failed"
        task.error_message = "Company not found"
        db.commit()
        return task

    task.status = "running"
    task.started_at = datetime.now(UTC)
    _log(db, task, "info", "Crawl task started")
    db.commit()

    target_question_ids = payload.target_question_ids if payload else task.target_question_ids
    keyword_ids = payload.keyword_ids if payload else task.keyword_ids
    questions, keywords, scope_mode = _resolve_crawl_scope(
        db,
        project,
        target_question_ids=target_question_ids,
        keyword_ids=keyword_ids,
    )

    providers = list(db.scalars(select(LLMProvider).where(LLMProvider.id.in_(task.provider_ids))))
    competitors = list(db.scalars(select(Competitor).where(Competitor.project_id == project.id)))

    blockers = _provider_blockers(db, task.provider_ids, providers)
    if not providers:
        blockers.append("没有可用的 active 真实 Provider，请先配置并选择模型渠道。")
    if blockers:
        task.status = "failed"
        task.error_message = "Provider preflight failed: " + "；".join(blockers)
        task.finished_at = datetime.now(UTC)
        db.add(task)
        _log(db, task, "error", "Provider preflight failed", {"blockers": blockers})
        db.commit()
        db.refresh(task)
        return task

    prompts: list[tuple[str, int | None, int | None]] = [
        (question.question_text, question.id, None) for question in questions
    ]
    for keyword in keywords:
        prompts.extend(
            (prompt_text, None, keyword.id)
            for prompt_text in build_keyword_prompt_variants(keyword.keyword, project.target_industry)
        )
    run_count = max(1, task.sample_runs_per_prompt or 1)
    total_call_count = len(prompts) * len(providers) * run_count
    _log(
        db,
        task,
        "info",
        "Crawl scope resolved",
        {
            "scope_mode": scope_mode,
            "target_question_count": len(questions),
            "keyword_count": len(keywords),
            "provider_count": len(providers),
            "sample_runs_per_prompt": run_count,
            "total_call_count": total_call_count,
        },
    )

    completed_count = 0
    failed_count = 0
    company_snapshot = SimpleNamespace(
        id=company.id,
        name=company.name,
        brand_aliases=list(company.brand_aliases or []),
        website_url=company.website_url,
        industry=company.industry,
    )
    project_snapshot = SimpleNamespace(
        id=project.id,
        name=project.name,
        company_id=project.company_id,
        target_industry=project.target_industry,
    )
    competitor_snapshots = [
        SimpleNamespace(id=item.id, name=item.name, aliases=list(item.aliases or []))
        for item in competitors
    ]
    for provider in providers:
        provider_snapshot = SimpleNamespace(
            id=provider.id,
            name=provider.name,
            provider_type=provider.provider_type,
            api_base_url=provider.api_base_url,
            model_name=provider.model_name,
            auth_config=dict(provider.auth_config or {}),
            cost_rule=dict(provider.cost_rule or {}),
            status=provider.status,
        )
        search_provider = get_search_provider(provider_snapshot)
        max_concurrency = max(1, min(int((provider.cost_rule or {}).get("max_concurrency", 1) or 1), 4))
        _log(
            db,
            task,
            "info",
            "Provider started",
            {"provider_id": provider.id, "name": provider.name, "max_concurrency": max_concurrency},
        )
        db.commit()
        for prompt_text, question_id, keyword_id in prompts:
            existing_stmt = (
                select(func.count())
                .select_from(CrawlResult)
                .where(
                    CrawlResult.task_id == task.id,
                    CrawlResult.provider_id == provider.id,
                    CrawlResult.prompt_text == prompt_text,
                )
            )
            existing_stmt = existing_stmt.where(
                CrawlResult.target_question_id == question_id
                if question_id is not None
                else CrawlResult.target_question_id.is_(None),
                CrawlResult.keyword_id == keyword_id
                if keyword_id is not None
                else CrawlResult.keyword_id.is_(None),
            )
            existing_count = int(db.scalar(existing_stmt) or 0)
            completed_count += min(existing_count, run_count)
            missing_runs = list(range(existing_count + 1, run_count + 1))
            if not missing_runs:
                continue
            for sample_run in missing_runs:
                _log(db, task, "info", "Prompt queued", {"prompt_text": prompt_text, "sample_run": sample_run})
            db.commit()
            enforce_monthly_search_budget(db, provider, projected_calls=len(missing_runs))
            with ThreadPoolExecutor(max_workers=min(max_concurrency, len(missing_runs))) as executor:
                futures = {
                    executor.submit(
                        search_provider.answer,
                        prompt_text,
                        company_snapshot,
                        project_snapshot,
                        competitor_snapshots,
                    ): sample_run
                    for sample_run in missing_runs
                }
                for future in as_completed(futures):
                    sample_run = futures[future]
                    try:
                        provider_answer = future.result()
                        result = CrawlResult(
                            task_id=task.id,
                            project_id=project.id,
                            target_question_id=question_id,
                            keyword_id=keyword_id,
                            provider_id=provider.id,
                            prompt_text=provider_answer.prompt_text,
                            raw_answer=provider_answer.raw_answer,
                            answer_summary=provider_answer.answer_summary,
                            status="success",
                            collected_at=datetime.now(UTC),
                        )
                        db.add(result)
                        db.flush()
                        record_usage(
                            db,
                            provider=provider,
                            action="crawl.answer",
                            prompt_text=provider_answer.prompt_text,
                            completion_text=provider_answer.raw_answer,
                            company_id=company.id,
                            project_id=project.id,
                            task_id=task.id,
                            crawl_result_id=result.id,
                            detail={
                                "target_question_id": question_id,
                                "keyword_id": keyword_id,
                                "sample_run": sample_run,
                                "sample_runs_per_prompt": run_count,
                            },
                        )
                        analyze_answer(db, result, company, competitors)
                        _log(db, task, "info", "Prompt completed", {"crawl_result_id": result.id, "sample_run": sample_run})
                        completed_count += 1
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        task = db.get(CrawlTask, task.id)
                        failed_count += 1
                        _log(
                            db,
                            task,
                            "error",
                            "Prompt failed; completed results were preserved",
                            {
                                "provider_id": provider.id,
                                "prompt_text": prompt_text,
                                "sample_run": sample_run,
                                "error": str(exc),
                            },
                        )
                        db.commit()

    task = db.get(CrawlTask, task.id)
    task.status = "success" if failed_count == 0 else "partial_success" if completed_count else "failed"
    task.error_message = None if failed_count == 0 else f"{failed_count}/{total_call_count} calls failed"
    task.finished_at = datetime.now(UTC)
    _log(
        db,
        task,
        "info" if failed_count == 0 else "warning",
        "Crawl task completed",
        {"expected_count": total_call_count, "result_count": completed_count, "failed_count": failed_count},
    )
    db.commit()
    db.refresh(task)
    return task
