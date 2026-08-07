import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime

from app.core.config import get_settings


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(digest, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: int, expires_in_seconds: int = 60 * 60 * 24 * 7) -> str:
    settings = get_settings()
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + expires_in_seconds,
        "iat": int(time.time()),
    }
    encoded_payload = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.auth_secret.encode(), encoded_payload.encode(), hashlib.sha256
    ).digest()
    return f"{encoded_payload}.{_b64(signature)}"


def decode_access_token(token: str) -> int | None:
    settings = get_settings()
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(
            settings.auth_secret.encode(), encoded_payload.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64(expected), encoded_signature):
            return None
        payload = json.loads(_unb64(encoded_payload))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return int(payload["sub"])
    except Exception:
        return None


def utcnow() -> datetime:
    return datetime.now(UTC)

