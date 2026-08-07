from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_project_or_404, require_project_access, require_roles
from app.db.session import get_db
from app.models import Competitor, Keyword, TargetQuestion
from app.schemas.common import APIMessage
from app.schemas.geo_config import (
    CompetitorCreate,
    CompetitorRead,
    CompetitorUpdate,
    KeywordCreate,
    KeywordRead,
    KeywordUpdate,
    TargetQuestionCreate,
    TargetQuestionRead,
    TargetQuestionUpdate,
)

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["geo-config"],
    dependencies=[Depends(require_project_access)],
)

T = TypeVar("T", TargetQuestion, Keyword, Competitor)


def get_child_or_404(db: Session, model: type[T], project_id: int, item_id: int) -> T:
    item = db.get(model, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return item


@router.get("/target-questions", response_model=list[TargetQuestionRead])
def list_target_questions(project_id: int, db: Session = Depends(get_db)) -> list[TargetQuestion]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(TargetQuestion)
            .where(TargetQuestion.project_id == project_id)
            .order_by(TargetQuestion.priority.asc(), TargetQuestion.created_at.desc())
        )
    )


@router.post("/target-questions", response_model=TargetQuestionRead, status_code=201)
def create_target_question(
    project_id: int,
    payload: TargetQuestionCreate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> TargetQuestion:
    get_project_or_404(db, project_id)
    item = TargetQuestion(project_id=project_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/target-questions/bulk", response_model=list[TargetQuestionRead], status_code=201)
def bulk_create_target_questions(
    project_id: int,
    payload: list[TargetQuestionCreate],
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> list[TargetQuestion]:
    get_project_or_404(db, project_id)
    items = [TargetQuestion(project_id=project_id, **item.model_dump()) for item in payload]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return items


@router.patch("/target-questions/{item_id}", response_model=TargetQuestionRead)
def update_target_question(
    project_id: int,
    item_id: int,
    payload: TargetQuestionUpdate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> TargetQuestion:
    item = get_child_or_404(db, TargetQuestion, project_id, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/target-questions/{item_id}", response_model=APIMessage)
def delete_target_question(
    project_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> APIMessage:
    item = get_child_or_404(db, TargetQuestion, project_id, item_id)
    db.delete(item)
    db.commit()
    return APIMessage(message="Target question deleted")


@router.get("/keywords", response_model=list[KeywordRead])
def list_keywords(project_id: int, db: Session = Depends(get_db)) -> list[Keyword]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(Keyword)
            .where(Keyword.project_id == project_id)
            .order_by(Keyword.priority.asc(), Keyword.created_at.desc())
        )
    )


@router.post("/keywords", response_model=KeywordRead, status_code=201)
def create_keyword(
    project_id: int,
    payload: KeywordCreate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> Keyword:
    get_project_or_404(db, project_id)
    item = Keyword(project_id=project_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/keywords/bulk", response_model=list[KeywordRead], status_code=201)
def bulk_create_keywords(
    project_id: int,
    payload: list[KeywordCreate],
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> list[Keyword]:
    get_project_or_404(db, project_id)
    items = [Keyword(project_id=project_id, **item.model_dump()) for item in payload]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return items


@router.patch("/keywords/{item_id}", response_model=KeywordRead)
def update_keyword(
    project_id: int,
    item_id: int,
    payload: KeywordUpdate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> Keyword:
    item = get_child_or_404(db, Keyword, project_id, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/keywords/{item_id}", response_model=APIMessage)
def delete_keyword(
    project_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> APIMessage:
    item = get_child_or_404(db, Keyword, project_id, item_id)
    db.delete(item)
    db.commit()
    return APIMessage(message="Keyword deleted")


@router.get("/competitors", response_model=list[CompetitorRead])
def list_competitors(project_id: int, db: Session = Depends(get_db)) -> list[Competitor]:
    get_project_or_404(db, project_id)
    return list(
        db.scalars(
            select(Competitor)
            .where(Competitor.project_id == project_id)
            .order_by(Competitor.created_at.desc())
        )
    )


@router.post("/competitors", response_model=CompetitorRead, status_code=201)
def create_competitor(
    project_id: int,
    payload: CompetitorCreate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> Competitor:
    get_project_or_404(db, project_id)
    item = Competitor(project_id=project_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/competitors/{item_id}", response_model=CompetitorRead)
def update_competitor(
    project_id: int,
    item_id: int,
    payload: CompetitorUpdate,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> Competitor:
    item = get_child_or_404(db, Competitor, project_id, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/competitors/{item_id}", response_model=APIMessage)
def delete_competitor(
    project_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles(*WRITE_ROLES)),
) -> APIMessage:
    item = get_child_or_404(db, Competitor, project_id, item_id)
    db.delete(item)
    db.commit()
    return APIMessage(message="Competitor deleted")
