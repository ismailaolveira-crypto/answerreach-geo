from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import GeoWorkspace
from app.models.user import User
from app.services.workspace_access import require_workspace_access


def workspace_or_404(db: Session, user: User, workspace_id: int) -> GeoWorkspace:
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    return workspace


def scoped_or_404(db: Session, model: type, workspace_id: int, item_id: int):
    item = db.get(model, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return item
