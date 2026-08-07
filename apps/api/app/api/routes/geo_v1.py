from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_project_or_404, require_project_access, require_roles
from app.db.session import get_db
from app.models import (
    AnswerAnalysis,
    BrandClaim,
    CitationSource,
    CrawlResult,
    LLMProvider,
    MentionedEntity,
    ObservationReview,
    OptimizationAction,
    TargetQuestion,
    User,
)
from app.schemas.geo_v1 import (
    BrandClaimCreate,
    BrandClaimRead,
    BrandClaimUpdate,
    DecisionMapCell,
    DecisionMapMetric,
    DecisionMapQuestion,
    DecisionMapRead,
    ObservationRead,
    ObservationReviewRead,
    ObservationReviewUpsert,
    OptimizationActionCreate,
    OptimizationActionRead,
    OptimizationActionUpdate,
)
from app.services.audit import record_audit_log


router = APIRouter(
    prefix="/projects/{project_id}/geo-v1",
    tags=["geo-v1"],
    dependencies=[Depends(require_project_access)],
)


def _collection_method(provider: LLMProvider | None) -> tuple[str, bool]:
    if provider is None:
        return "manual_import", False
    if provider.provider_type == "mock":
        return "mock", False
    if provider.provider_type == "browser_observation":
        return "web_ui_observation", True
    if provider.provider_type in {"kimi_web_search", "hunyuan_web_search"} or bool((provider.cost_rule or {}).get("enable_search")):
        return "web_search_api", True
    return "api", True


def _review_read(review: ObservationReview | None) -> ObservationReviewRead | None:
    return ObservationReviewRead.model_validate(review) if review is not None else None


def _brand_status(
    result: CrawlResult,
    analysis: AnswerAnalysis | None,
    review: ObservationReview | None,
    owned_or_placed_citation_count: int,
) -> str:
    if result.status not in {"success", "partial_success"}:
        return "failed"
    if review is not None and review.claim_accuracy == "inaccurate":
        return "insufficient"
    mentioned = review.company_mentioned if review and review.company_mentioned is not None else bool(analysis and analysis.company_mentioned)
    shortlisted = bool(review and review.company_shortlisted)
    recommended = review.company_recommended if review and review.company_recommended is not None else bool(analysis and analysis.company_recommended)
    citation_valid = review.citation_valid if review and review.citation_valid is not None else owned_or_placed_citation_count > 0
    if mentioned and citation_valid:
        return "cited"
    if recommended:
        return "recommended"
    if shortlisted:
        return "shortlisted"
    if mentioned:
        return "mentioned"
    return "absent"


def _observations(db: Session, project_id: int) -> list[ObservationRead]:
    results = list(
        db.scalars(
            select(CrawlResult)
            .where(CrawlResult.project_id == project_id)
            .order_by(CrawlResult.collected_at.desc(), CrawlResult.id.desc())
        )
    )
    questions = {item.id: item for item in db.scalars(select(TargetQuestion).where(TargetQuestion.project_id == project_id))}
    provider_ids = {item.provider_id for item in results if item.provider_id is not None}
    providers = {item.id: item for item in db.scalars(select(LLMProvider).where(LLMProvider.id.in_(provider_ids)))} if provider_ids else {}
    result_ids = [item.id for item in results]
    analyses = {item.crawl_result_id: item for item in db.scalars(select(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))} if result_ids else {}
    reviews = {item.crawl_result_id: item for item in db.scalars(select(ObservationReview).where(ObservationReview.crawl_result_id.in_(result_ids)))} if result_ids else {}
    citations: dict[int, list[CitationSource]] = defaultdict(list)
    entities: dict[int, list[MentionedEntity]] = defaultdict(list)
    if result_ids:
        for source in db.scalars(select(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids))):
            citations[source.crawl_result_id].append(source)
        for entity in db.scalars(select(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids))):
            entities[entity.crawl_result_id].append(entity)

    output: list[ObservationRead] = []
    for result in results:
        provider = providers.get(result.provider_id)
        question = questions.get(result.target_question_id)
        method, is_real_evidence = _collection_method(provider)
        result_citations = citations[result.id]
        owned_count = sum(1 for item in result_citations if item.is_owned or item.is_placed)
        analysis = analyses.get(result.id)
        review = reviews.get(result.id)
        output.append(
            ObservationRead(
                id=result.id,
                task_id=result.task_id,
                project_id=result.project_id,
                target_question_id=result.target_question_id,
                question_text=question.question_text if question else None,
                provider_id=result.provider_id,
                provider_name=provider.name if provider else "人工导入",
                provider_type=provider.provider_type if provider else "manual_import",
                collection_method=method,
                is_real_evidence=is_real_evidence,
                status=result.status,
                brand_status=_brand_status(result, analysis, review, owned_count),
                visibility_eligible=bool(question and question.counts_for_visibility and not question.contains_brand),
                prompt_text=result.prompt_text,
                answer_summary=result.answer_summary,
                raw_answer=result.raw_answer,
                collected_at=result.collected_at,
                confidence=analysis.confidence if analysis else None,
                citation_count=len(result_citations),
                owned_or_placed_citation_count=owned_count,
                competitors=[item.entity_name for item in entities[result.id] if item.is_competitor],
                review=_review_read(review),
            )
        )
    return output


def _get_result_or_404(db: Session, project_id: int, result_id: int) -> CrawlResult:
    result = db.get(CrawlResult, result_id)
    if result is None or result.project_id != project_id:
        raise HTTPException(status_code=404, detail="Observation not found")
    return result


def _validate_action_links(db: Session, project_id: int, target_question_id: int | None, result_ids: list[int], verification_result_id: int | None) -> None:
    if target_question_id is not None:
        question = db.get(TargetQuestion, target_question_id)
        if question is None or question.project_id != project_id:
            raise HTTPException(status_code=400, detail="Target question does not belong to project")
    for result_id in [*result_ids, *([verification_result_id] if verification_result_id else [])]:
        _get_result_or_404(db, project_id, result_id)


@router.get("/decision-map", response_model=DecisionMapRead)
def get_decision_map(project_id: int, db: Session = Depends(get_db)) -> DecisionMapRead:
    project = get_project_or_404(db, project_id)
    questions = list(db.scalars(select(TargetQuestion).where(TargetQuestion.project_id == project_id).order_by(TargetQuestion.priority.asc(), TargetQuestion.id.asc())))
    observations = _observations(db, project_id)
    latest: dict[tuple[int, int | None], ObservationRead] = {}
    for observation in observations:
        if observation.target_question_id is not None:
            latest.setdefault((observation.target_question_id, observation.provider_id), observation)
    provider_ids = sorted({item.provider_id for item in observations if item.provider_id is not None})
    providers = {item.id: item for item in db.scalars(select(LLMProvider).where(LLMProvider.id.in_(provider_ids)))} if provider_ids else {}
    eligible = [item for item in observations if item.visibility_eligible and item.is_real_evidence and item.status in {"success", "partial_success"}]
    cited = [item for item in eligible if item.brand_status == "cited"]
    recommended = [item for item in eligible if item.brand_status in {"recommended", "cited"}]
    pending_action_count = db.scalar(select(func.count()).select_from(OptimizationAction).where(OptimizationAction.project_id == project_id).where(OptimizationAction.status.not_in(["closed"]))) or 0
    cells = [
        DecisionMapCell(
            question_id=question_id,
            provider_id=provider_id,
            observation_id=observation.id,
            brand_status=observation.brand_status,
            collection_method=observation.collection_method,
            is_real_evidence=observation.is_real_evidence,
            collected_at=observation.collected_at,
        )
        for (question_id, provider_id), observation in latest.items()
    ]
    return DecisionMapRead(
        project_id=project.id,
        company_name=project.company.name,
        metrics=[
            DecisionMapMetric(key="organic_sample", label="自然提及样本", value=sum(item.brand_status != "absent" for item in eligible), help_text="仅统计不含品牌词且来自非 Mock 的成功观测。"),
            DecisionMapMetric(key="recommendation_rate", label="推荐率", value=round(len(recommended) / len(eligible) * 100, 1) if eligible else 0, help_text="推荐或引用的自然问题观测占比。"),
            DecisionMapMetric(key="citation_rate", label="自有信源引用率", value=round(len(cited) / len(eligible) * 100, 1) if eligible else 0, help_text="有已记录自有/投放信源的自然问题观测占比。"),
            DecisionMapMetric(key="fact_accuracy", label="事实准确率", value=round(sum(item.review and item.review.claim_accuracy == "accurate" for item in observations) / sum(item.review is not None for item in observations) * 100, 1) if any(item.review for item in observations) else 0, help_text="仅计算已人工复核的观测。"),
        ],
        questions=[DecisionMapQuestion(id=item.id, question_text=item.question_text, journey_stage=item.journey_stage, contains_brand=item.contains_brand, counts_for_visibility=item.counts_for_visibility, visibility_eligible=item.counts_for_visibility and not item.contains_brand) for item in questions],
        providers=[{"id": item.id, "name": item.name, "provider_type": item.provider_type} for item in providers.values()],
        cells=cells,
        pending_action_count=int(pending_action_count),
        data_notice="指标仅包含已持久化观测；Mock、网页端观测与 API 采集方式均会在证据中显式标注。",
    )


@router.get("/observations", response_model=list[ObservationRead])
def list_observations(project_id: int, q: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[ObservationRead]:
    observations = _observations(db, project_id)
    if not q:
        return observations
    needle = q.strip().lower()
    return [item for item in observations if needle in " ".join([item.question_text or "", item.provider_name, item.prompt_text, *item.competitors]).lower()]


@router.get("/observations/{result_id}", response_model=ObservationRead)
def get_observation(project_id: int, result_id: int, db: Session = Depends(get_db)) -> ObservationRead:
    _get_result_or_404(db, project_id, result_id)
    return next(item for item in _observations(db, project_id) if item.id == result_id)


@router.put("/observations/{result_id}/review", response_model=ObservationRead)
def upsert_observation_review(project_id: int, result_id: int, payload: ObservationReviewUpsert, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))) -> ObservationRead:
    result = _get_result_or_404(db, project_id, result_id)
    review = db.scalar(select(ObservationReview).where(ObservationReview.crawl_result_id == result.id))
    if review is None:
        review = ObservationReview(crawl_result_id=result.id, reviewer_user_id=user.id, **payload.model_dump())
        db.add(review)
    else:
        for field, value in payload.model_dump().items():
            setattr(review, field, value)
        review.reviewer_user_id = user.id
    record_audit_log(db, user=user, action="geo_v1.observation.review", resource_type="crawl_result", resource_id=result.id, project_id=project_id, company_id=get_project_or_404(db, project_id).company_id, detail=payload.model_dump(mode="json"))
    db.commit()
    return get_observation(project_id, result_id, db)


@router.get("/brand-claims", response_model=list[BrandClaimRead])
def list_brand_claims(project_id: int, db: Session = Depends(get_db)) -> list[BrandClaim]:
    get_project_or_404(db, project_id)
    return list(db.scalars(select(BrandClaim).where(BrandClaim.project_id == project_id).order_by(BrandClaim.updated_at.desc())))


@router.post("/brand-claims", response_model=BrandClaimRead, status_code=201)
def create_brand_claim(project_id: int, payload: BrandClaimCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))) -> BrandClaim:
    project = get_project_or_404(db, project_id)
    claim = BrandClaim(project_id=project_id, **payload.model_dump())
    db.add(claim)
    db.flush()
    record_audit_log(db, user=user, action="geo_v1.brand_claim.create", resource_type="brand_claim", resource_id=claim.id, project_id=project_id, company_id=project.company_id, detail={"title": claim.title})
    db.commit()
    db.refresh(claim)
    return claim


@router.patch("/brand-claims/{claim_id}", response_model=BrandClaimRead)
def update_brand_claim(project_id: int, claim_id: int, payload: BrandClaimUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))) -> BrandClaim:
    claim = db.get(BrandClaim, claim_id)
    if claim is None or claim.project_id != project_id:
        raise HTTPException(status_code=404, detail="Brand claim not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(claim, field, value)
    record_audit_log(db, user=user, action="geo_v1.brand_claim.update", resource_type="brand_claim", resource_id=claim.id, project_id=project_id, company_id=get_project_or_404(db, project_id).company_id, detail=payload.model_dump(exclude_unset=True, mode="json"))
    db.commit()
    db.refresh(claim)
    return claim


def _action_read(db: Session, action: OptimizationAction) -> OptimizationActionRead:
    question = db.get(TargetQuestion, action.target_question_id) if action.target_question_id else None
    return OptimizationActionRead(
        **{
            **OptimizationActionRead.model_validate(action).model_dump(),
            "question_text": question.question_text if question else None,
        }
    )


@router.get("/actions", response_model=list[OptimizationActionRead])
def list_actions(project_id: int, db: Session = Depends(get_db)) -> list[OptimizationActionRead]:
    get_project_or_404(db, project_id)
    return [_action_read(db, item) for item in db.scalars(select(OptimizationAction).where(OptimizationAction.project_id == project_id).order_by(OptimizationAction.updated_at.desc()))]


@router.post("/actions", response_model=OptimizationActionRead, status_code=201)
def create_action(project_id: int, payload: OptimizationActionCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))) -> OptimizationActionRead:
    project = get_project_or_404(db, project_id)
    _validate_action_links(db, project_id, payload.target_question_id, payload.source_result_ids, payload.verification_result_id)
    action = OptimizationAction(project_id=project_id, **payload.model_dump())
    db.add(action)
    db.flush()
    record_audit_log(db, user=user, action="geo_v1.action.create", resource_type="optimization_action", resource_id=action.id, project_id=project_id, company_id=project.company_id, detail={"title": action.title, "status": action.status})
    db.commit()
    db.refresh(action)
    return _action_read(db, action)


@router.patch("/actions/{action_id}", response_model=OptimizationActionRead)
def update_action(project_id: int, action_id: int, payload: OptimizationActionUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES))) -> OptimizationActionRead:
    action = db.get(OptimizationAction, action_id)
    if action is None or action.project_id != project_id:
        raise HTTPException(status_code=404, detail="Optimization action not found")
    changes = payload.model_dump(exclude_unset=True)
    target_question_id = changes.get("target_question_id", action.target_question_id)
    source_result_ids = changes.get("source_result_ids", action.source_result_ids or [])
    verification_result_id = changes.get("verification_result_id", action.verification_result_id)
    _validate_action_links(db, project_id, target_question_id, source_result_ids, verification_result_id)
    next_status = changes.get("status", action.status)
    verification_summary = changes.get("verification_summary", action.verification_summary)
    if next_status in {"verified", "closed"} and not (verification_result_id and verification_summary):
        raise HTTPException(status_code=400, detail="Verified or closed actions require a follow-up observation and conclusion")
    for field, value in changes.items():
        setattr(action, field, value)
    record_audit_log(db, user=user, action="geo_v1.action.update", resource_type="optimization_action", resource_id=action.id, project_id=project_id, company_id=get_project_or_404(db, project_id).company_id, detail=payload.model_dump(exclude_unset=True, mode="json"))
    db.commit()
    db.refresh(action)
    return _action_read(db, action)
