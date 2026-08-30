import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.auth import AuthLoginThrottle, AuthSession, SecurityRateLimit
from app.models.user import User

PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 120_000
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_LOCK = timedelta(minutes=15)
LOGIN_FAILURE_LIMIT = 5


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    expires_at: datetime
    issued_at: datetime
    jti: str
    credentials_version: int


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
    f"pbkdf2_sha256${PBKDF2_ITERATIONS}$00000000000000000000000000000000$"
    + _password_digest(
        "not-a-real-account-password",
        "00000000000000000000000000000000",
        PBKDF2_ITERATIONS,
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


def _token_digest(jti: str) -> str:
    settings = get_settings()
    return hmac.new(settings.auth_secret.encode(), jti.encode(), hashlib.sha256).hexdigest()


def _encode_access_token(
    user_id: int,
    *,
    jti: str,
    credentials_version: int,
    expires_in_seconds: int,
) -> str:
    settings = get_settings()
    issued_at = int(time.time())
    payload = {
        "sub": user_id,
        "exp": issued_at + expires_in_seconds,
        "iat": issued_at,
        "jti": jti,
        "ver": credentials_version,
    }
    encoded_payload = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.auth_secret.encode(), encoded_payload.encode(), hashlib.sha256
    ).digest()
    return f"{encoded_payload}.{_b64(signature)}"


def issue_access_token(
    db: Session,
    user: User,
    expires_in_seconds: int = 60 * 60 * 24,
) -> str:
    """Issue a signed token backed by a revocable server-side session."""

    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    jti = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=expires_in_seconds)
    db.add(
        AuthSession(
            user_id=user.id,
            jti_hash=_token_digest(jti),
            expires_at=expires_at,
        )
    )
    return _encode_access_token(
        user.id,
        jti=jti,
        credentials_version=user.credentials_version,
        expires_in_seconds=expires_in_seconds,
    )


def decode_access_token(token: str) -> AccessTokenClaims | None:
    settings = get_settings()
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(
            settings.auth_secret.encode(), encoded_payload.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64(expected), encoded_signature):
            return None
        payload = json.loads(_unb64(encoded_payload))
        expires_at = int(payload.get("exp", 0))
        issued_at = int(payload.get("iat", 0))
        jti = str(payload.get("jti") or "")
        credentials_version = int(payload.get("ver", 0))
        if expires_at <= int(time.time()) or issued_at <= 0:
            return None
        if len(jti) < 32 or credentials_version < 1:
            return None
        return AccessTokenClaims(
            user_id=int(payload["sub"]),
            expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
            issued_at=datetime.fromtimestamp(issued_at, tz=UTC),
            jti=jti,
            credentials_version=credentials_version,
        )
    except Exception:
        return None


def active_session(db: Session, claims: AccessTokenClaims) -> AuthSession | None:
    now = utcnow()
    return db.scalar(
        select(AuthSession).where(
            AuthSession.user_id == claims.user_id,
            AuthSession.jti_hash == _token_digest(claims.jti),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )


def revoke_session(db: Session, session: AuthSession) -> None:
    session.revoked_at = utcnow()


def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def security_rate_limit_key(scope: str, identity: str) -> str:
    settings = get_settings()
    value = f"{scope}\0{identity.strip().lower()}".encode()
    return hmac.new(settings.auth_secret.encode(), value, hashlib.sha256).hexdigest()


def consume_security_rate_limit(
    db: Session,
    *,
    scope: str,
    identity: str,
    limit: int,
    window: timedelta,
    now: datetime | None = None,
) -> int:
    """Consume one persistent bucket slot; return retry seconds when blocked."""

    current = now or utcnow()
    key_hash = security_rate_limit_key(scope, identity)
    row = db.scalar(
        select(SecurityRateLimit)
        .where(SecurityRateLimit.key_hash == key_hash)
        .with_for_update()
    )
    if row is None:
        db.add(
            SecurityRateLimit(
                key_hash=key_hash,
                request_count=1,
                window_started_at=current,
            )
        )
        db.flush()
        return 0
    blocked_until = row.blocked_until
    if blocked_until is not None:
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=UTC)
        if blocked_until > current:
            return max(1, int((blocked_until - current).total_seconds()) + 1)
    window_started_at = row.window_started_at
    if window_started_at.tzinfo is None:
        window_started_at = window_started_at.replace(tzinfo=UTC)
    if current - window_started_at >= window:
        row.request_count = 1
        row.window_started_at = current
        row.blocked_until = None
        return 0
    if row.request_count >= max(1, limit):
        row.blocked_until = window_started_at + window
        return max(1, int((row.blocked_until - current).total_seconds()) + 1)
    row.request_count += 1
    return 0


def security_rate_limit_retry_after(
    db: Session,
    *,
    scope: str,
    identity: str,
    limit: int,
    window: timedelta,
    now: datetime | None = None,
) -> int:
    """Read a persistent bucket without consuming a successful request."""

    current = now or utcnow()
    row = db.scalar(
        select(SecurityRateLimit).where(
            SecurityRateLimit.key_hash == security_rate_limit_key(scope, identity)
        )
    )
    if row is None:
        return 0
    blocked_until = row.blocked_until
    if blocked_until is not None:
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=UTC)
        if blocked_until > current:
            return max(1, int((blocked_until - current).total_seconds()) + 1)
    window_started_at = row.window_started_at
    if window_started_at.tzinfo is None:
        window_started_at = window_started_at.replace(tzinfo=UTC)
    if current - window_started_at >= window:
        db.delete(row)
    elif row.request_count >= max(1, limit):
        return max(1, int(((window_started_at + window) - current).total_seconds()) + 1)
    return 0


def utcnow() -> datetime:
    return datetime.now(UTC)
