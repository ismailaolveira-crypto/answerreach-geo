import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.auth import AuthLoginThrottle

PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 120_000
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_LOCK = timedelta(minutes=15)
LOGIN_FAILURE_LIMIT = 5


def canonicalize_email(email: str) -> str:
    """Return the single account identity used for lookups and persistence."""

    return email.strip().lower()


def login_throttle_key(email: str, client_host: str) -> str:
    settings = get_settings()
    value = f"{canonicalize_email(email)}\0{client_host.strip().lower()}".encode()
    return hmac.new(settings.auth_secret.encode(), value, hashlib.sha256).hexdigest()


def login_retry_after(db: Session, key_hash: str, *, now: datetime | None = None) -> int:
    current = now or utcnow()
    row = db.scalar(select(AuthLoginThrottle).where(AuthLoginThrottle.key_hash == key_hash))
    if row is None or row.locked_until is None:
        return 0
    locked_until = row.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return max(0, int((locked_until - current).total_seconds()) + 1)


def record_login_failure(
    db: Session, key_hash: str, *, now: datetime | None = None
) -> None:
    current = now or utcnow()
    db.execute(
        delete(AuthLoginThrottle).where(
            AuthLoginThrottle.window_started_at < current - timedelta(days=1)
        )
    )
    row = db.scalar(
        select(AuthLoginThrottle)
        .where(AuthLoginThrottle.key_hash == key_hash)
        .with_for_update()
    )
    if row is None:
        row = AuthLoginThrottle(
            key_hash=key_hash,
            failure_count=1,
            window_started_at=current,
        )
        db.add(row)
    else:
        window_started_at = row.window_started_at
        if window_started_at.tzinfo is None:
            window_started_at = window_started_at.replace(tzinfo=UTC)
        if current - window_started_at >= LOGIN_WINDOW:
            row.failure_count = 1
            row.window_started_at = current
            row.locked_until = None
        else:
            row.failure_count += 1
    if row.failure_count >= LOGIN_FAILURE_LIMIT:
        row.locked_until = current + LOGIN_LOCK


def clear_login_failures(db: Session, key_hash: str) -> None:
    db.execute(delete(AuthLoginThrottle).where(AuthLoginThrottle.key_hash == key_hash))


def _password_digest(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    ).hex()


DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$120000$00000000000000000000000000000000$"
    + _password_digest(
        "not-a-real-account-password",
        "00000000000000000000000000000000",
        LEGACY_PBKDF2_ITERATIONS,
    )
)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = _password_digest(password, salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        parts = password_hash.split("$")
    except ValueError:
        return False
    if len(parts) == 4:
        algorithm, iteration_text, salt, expected = parts
        try:
            iterations = int(iteration_text)
        except ValueError:
            return False
    elif len(parts) == 3:
        algorithm, salt, expected = parts
        iterations = LEGACY_PBKDF2_ITERATIONS
    else:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    if iterations < LEGACY_PBKDF2_ITERATIONS or iterations > 2_000_000:
        return False
    digest = _password_digest(password, salt, iterations)
    return hmac.compare_digest(digest, expected)


def password_needs_rehash(password_hash: str | None) -> bool:
    if not password_hash:
        return True
    parts = password_hash.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return True
    try:
        return int(parts[1]) != PBKDF2_ITERATIONS
    except ValueError:
        return True


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: int, expires_in_seconds: int = 60 * 60 * 24) -> str:
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
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return int(payload["sub"])
    except Exception:
        return None


def utcnow() -> datetime:
    return datetime.now(UTC)
