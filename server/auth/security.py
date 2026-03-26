"""Security utilities: password hashing, JWT creation/verification, lockout logic."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY: str = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))   # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
MAX_FAILED_ATTEMPTS: int = int(os.getenv("MAX_FAILED_ATTEMPTS", "5"))
LOCKOUT_MINUTES: int = int(os.getenv("LOCKOUT_MINUTES", "30"))

# ── Password hashing ──────────────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def validate_password_strength(password: str) -> list[str]:
    """Return list of unmet requirements (empty = valid)."""
    errors = []
    if len(password) < 10:
        errors.append("Must be at least 10 characters")
    if not any(c.isupper() for c in password):
        errors.append("Must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("Must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("Must contain at least one number")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        errors.append("Must contain at least one special character")
    return errors


# ── JWT tokens ────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, username: str, role: str,
                        expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> tuple[str, str, datetime]:
    """Return (encoded_token, jti, expires_at)."""
    jti = str(uuid.uuid4())
    expires_at = _utcnow() + timedelta(minutes=expires_minutes)
    payload = {
        "sub":      user_id,
        "username": username,
        "role":     role,
        "jti":      jti,
        "iat":      _utcnow(),
        "exp":      expires_at,
        "type":     "access",
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, jti, expires_at


def create_refresh_token(user_id: str, expires_days: int = REFRESH_TOKEN_EXPIRE_DAYS) -> tuple[str, str, datetime]:
    """Return (encoded_token, jti, expires_at)."""
    jti = str(uuid.uuid4())
    expires_at = _utcnow() + timedelta(days=expires_days)
    payload = {
        "sub":  user_id,
        "jti":  jti,
        "iat":  _utcnow(),
        "exp":  expires_at,
        "type": "refresh",
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises JWTError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ── Account lockout ───────────────────────────────────────────────────────────

def is_account_locked(user: dict) -> bool:
    locked_until = user.get("locked_until")
    if not locked_until:
        return False
    try:
        lock_dt = datetime.fromisoformat(locked_until).replace(tzinfo=timezone.utc)
        return _utcnow() < lock_dt
    except ValueError:
        return False


def lockout_expires_at(user: dict) -> str:
    return user.get("locked_until", "")


def should_lock(failed_attempts: int) -> bool:
    return failed_attempts >= MAX_FAILED_ATTEMPTS


def lock_until_str() -> str:
    return (_utcnow() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
