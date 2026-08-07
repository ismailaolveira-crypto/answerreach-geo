"""Secret storage and runtime resolution for workspace integrations."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.cleanroom_v1 import GeoWorkspaceSecret
from app.services.article_sync_adapter import DEFAULT_ARTICLE_SYNC_MCP_URL

DEEPSEEK_API_KEY = "deepseek_api_key"
ARTICLE_SYNC_MCP_URL = "article_sync_mcp_url"
ARTICLE_SYNC_MCP_TOKEN = "article_sync_mcp_token"


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().auth_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("workspace_secret_decrypt_failed") from exc


def get_workspace_secret(db: Session, workspace_id: int, key: str) -> str | None:
    row = db.scalar(
        select(GeoWorkspaceSecret).where(
            GeoWorkspaceSecret.workspace_id == workspace_id,
            GeoWorkspaceSecret.secret_key == key,
        )
    )
    if row is None:
        return None
    return decrypt_secret(row.encrypted_value)


def set_workspace_secret(
    db: Session,
    *,
    workspace_id: int,
    key: str,
    value: str,
    user_id: int | None,
) -> GeoWorkspaceSecret:
    row = db.scalar(
        select(GeoWorkspaceSecret).where(
            GeoWorkspaceSecret.workspace_id == workspace_id,
            GeoWorkspaceSecret.secret_key == key,
        )
    )
    if row is None:
        row = GeoWorkspaceSecret(workspace_id=workspace_id, secret_key=key, encrypted_value="")
        db.add(row)
    row.encrypted_value = encrypt_secret(value)
    row.updated_by_user_id = user_id
    return row


def resolve_article_sync_credentials(db: Session, workspace_id: int) -> tuple[str | None, str | None]:
    """Workspace settings take precedence; env remains a deployment fallback."""
    settings = get_settings()
    endpoint = get_workspace_secret(db, workspace_id, ARTICLE_SYNC_MCP_URL) or settings.article_sync_mcp_url or DEFAULT_ARTICLE_SYNC_MCP_URL
    token = get_workspace_secret(db, workspace_id, ARTICLE_SYNC_MCP_TOKEN) or settings.article_sync_mcp_token
    return endpoint, token


def secret_status(db: Session, workspace_id: int, key: str) -> dict[str, object]:
    row = db.scalar(
        select(GeoWorkspaceSecret).where(
            GeoWorkspaceSecret.workspace_id == workspace_id,
            GeoWorkspaceSecret.secret_key == key,
        )
    )
    return {"configured": row is not None, "updated_at": row.updated_at if row else None}
