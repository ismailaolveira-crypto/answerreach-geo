import hashlib

from app.services.auth import (
    PBKDF2_ITERATIONS,
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_password_hash_records_current_work_factor() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.split("$", 2)[:2] == ["pbkdf2_sha256", str(PBKDF2_ITERATIONS)]
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong password", encoded) is False
    assert password_needs_rehash(encoded) is False


def test_legacy_password_hash_remains_valid_but_requires_upgrade() -> None:
    password = "legacy password"
    salt = "0123456789abcdef0123456789abcdef"
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 120_000
    ).hex()
    legacy = f"pbkdf2_sha256${salt}${digest}"
    assert verify_password(password, legacy) is True
    assert password_needs_rehash(legacy) is True
