from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import ReviewRule, User
from app.schemas.content import ReviewRuleCreate, ReviewRuleRead, ReviewRuleUpdate
from app.services.audit import record_audit_log
from app.services.review_rules import seed_default_review_rules

router = APIRouter(prefix="/review-rules", tags=["review-rules"])


def get_review_rule_or_404(db: Session, rule_id: int) -> ReviewRule:
    rule = db.get(ReviewRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Review rule not found")
    return rule


@router.get("", response_model=list[ReviewRuleRead])
def list_review_rules(
    status: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("super_admin", "company_admin", "reviewer")),
) -> list[ReviewRule]:
    seed_default_review_rules(db)
    stmt = select(ReviewRule).order_by(ReviewRule.status.asc(), ReviewRule.id.asc())
    if status is not None:
        stmt = stmt.where(ReviewRule.status == status)
    return list(db.scalars(stmt))


@router.post("", response_model=ReviewRuleRead, status_code=201)
def create_review_rule(
    payload: ReviewRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> ReviewRule:
    rule = ReviewRule(**payload.model_dump())
    db.add(rule)
    db.flush()
    record_audit_log(
        db,
        user=user,
        action="review_rule.create",
        resource_type="review_rule",
        resource_id=rule.id,
        detail={"rule_key": rule.rule_key, "name": rule.name, "max_score": rule.max_score},
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=ReviewRuleRead)
def update_review_rule(
    rule_id: int,
    payload: ReviewRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
) -> ReviewRule:
    rule = get_review_rule_or_404(db, rule_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)
    if update_data and "version" not in update_data:
        rule.version += 1
    record_audit_log(
        db,
        user=user,
        action="review_rule.update",
        resource_type="review_rule",
        resource_id=rule.id,
        detail={"updated_fields": list(update_data.keys()), "version": rule.version},
    )
    db.commit()
    db.refresh(rule)
    return rule
