"""Authentication API routes.

POST /api/auth/login          — issue access + refresh tokens
POST /api/auth/logout         — revoke current session
POST /api/auth/refresh        — exchange refresh token for new access token
GET  /api/auth/me             — current user info + active sessions
POST /api/auth/change-password
DELETE /api/auth/sessions/{jti} — revoke a specific session
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from server import database as db
from server.auth import security as sec
from server.auth.models import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
    UserPublic,
    UserSession,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# ── Dependency: get current user from Bearer token ────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Validate Bearer token and return the user dict. Raises 401 on failure."""
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = sec.decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")

    jti = payload.get("jti")
    session = db.get_session_by_jti(jti)
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked or not found")

    # Check expiry
    expires_at = datetime.fromisoformat(session["expires_at"]).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        db.revoke_session(jti)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user = db.get_user_by_id(payload["sub"])
    if not user or not user["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account inactive")

    db.touch_session(jti)
    user["_jti"] = jti
    user["_session_expires_at"] = session["expires_at"]
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")

    user = db.get_user_by_username(body.username)

    # Generic error to prevent username enumeration
    _invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user:
        db.audit("login_failed", username=body.username, ip_address=ip,
                 details={"reason": "unknown_user"})
        raise _invalid

    if not user["is_active"]:
        db.audit("login_failed", user_id=user["id"], username=user["username"],
                 ip_address=ip, details={"reason": "inactive"})
        raise _invalid

    if sec.is_account_locked(user):
        db.audit("login_failed", user_id=user["id"], username=user["username"],
                 ip_address=ip, details={"reason": "locked"})
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account locked until {sec.lockout_expires_at(user)} UTC due to too many failed attempts.",
        )

    if not sec.verify_password(body.password, user["password_hash"]):
        count = db.record_failed_login(user["id"])
        if sec.should_lock(count):
            db.update_user(user["id"], locked_until=sec.lock_until_str())
            db.audit("locked", user_id=user["id"], username=user["username"],
                     ip_address=ip, details={"failed_attempts": count})
        else:
            db.audit("login_failed", user_id=user["id"], username=user["username"],
                     ip_address=ip, details={"failed_attempts": count})
        raise _invalid

    # Successful login
    db.reset_failed_attempts(user["id"])
    access_token, access_jti, access_expires = sec.create_access_token(
        user["id"], user["username"], user["role"]
    )
    refresh_token, _, _ = sec.create_refresh_token(user["id"])

    db.create_session(
        user_id=user["id"],
        token_jti=access_jti,
        expires_at=access_expires.isoformat(),
        ip_address=ip,
        user_agent=user_agent,
    )
    db.audit("login", user_id=user["id"], username=user["username"], ip_address=ip)

    expires_in = int((access_expires - datetime.now(timezone.utc)).total_seconds())
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        expires_at=access_expires.isoformat(),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: dict = Depends(get_current_user)):
    db.revoke_session(current_user["_jti"])
    db.audit("logout", user_id=current_user["id"], username=current_user["username"])


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, request: Request):
    ip = request.client.host if request.client else ""
    try:
        payload = sec.decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")

    user = db.get_user_by_id(payload["sub"])
    if not user or not user["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account inactive")

    user_agent = request.headers.get("user-agent", "")
    access_token, access_jti, access_expires = sec.create_access_token(
        user["id"], user["username"], user["role"]
    )
    new_refresh, _, _ = sec.create_refresh_token(user["id"])

    db.create_session(
        user_id=user["id"],
        token_jti=access_jti,
        expires_at=access_expires.isoformat(),
        ip_address=ip,
        user_agent=user_agent,
    )

    expires_in = int((access_expires - datetime.now(timezone.utc)).total_seconds())
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=expires_in,
        expires_at=access_expires.isoformat(),
    )


@router.get("/me", response_model=MeResponse)
async def me(current_user: dict = Depends(get_current_user)):
    sessions = db.list_user_sessions(current_user["id"])
    return MeResponse(
        user=UserPublic(
            id=current_user["id"],
            username=current_user["username"],
            email=current_user["email"],
            role=current_user["role"],
            is_active=bool(current_user["is_active"]),
            created_at=current_user["created_at"],
            last_login=current_user.get("last_login"),
        ),
        sessions=[UserSession(**s) for s in sessions],
        session_expires_at=current_user["_session_expires_at"],
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if not sec.verify_password(body.current_password, current_user["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    db.update_user(current_user["id"], password_hash=sec.hash_password(body.new_password))
    # Revoke all sessions to force re-login everywhere
    db.revoke_all_user_sessions(current_user["id"])
    db.audit("password_changed", user_id=current_user["id"],
             username=current_user["username"])


@router.delete("/sessions/{jti}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(jti: str, current_user: dict = Depends(get_current_user)):
    """Revoke a specific session (e.g. sign out from a specific device)."""
    session = db.get_session_by_jti(jti)
    if not session or session["user_id"] != current_user["id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    db.revoke_session(jti)
