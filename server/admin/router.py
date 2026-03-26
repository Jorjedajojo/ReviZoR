"""Admin API routes — all require role=admin.

GET    /api/admin/users              — list all users
POST   /api/admin/users              — create a user
PUT    /api/admin/users/{id}         — update user (role, active status)
DELETE /api/admin/users/{id}         — deactivate user (never hard-delete)
POST   /api/admin/users/{id}/unlock  — unlock a locked account
POST   /api/admin/users/{id}/reset-sessions — revoke all sessions for a user
GET    /api/admin/audit-log          — full audit log
GET    /api/admin/audit-log/{user_id} — audit log for one user
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from server import database as db
from server.auth import security as sec
from server.auth.router import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Request models ────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(_: dict = Depends(require_admin)):
    return db.list_users()


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    admin: dict = Depends(require_admin),
):
    errors = sec.validate_password_strength(body.password)
    if errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "; ".join(errors))

    existing = db.get_user_by_username(body.username)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")

    uid = db.create_user(
        username=body.username,
        email=body.email,
        password_hash=sec.hash_password(body.password),
        role=body.role,
        created_by=admin["id"],
    )
    db.audit("user_created", user_id=admin["id"], username=admin["username"],
             details={"new_user": body.username, "role": body.role})
    return {"id": uid, "username": body.username, "role": body.role}


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    admin: dict = Depends(require_admin),
):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot modify your own account via admin API")

    updates = {}
    if body.role is not None:
        updates["role"] = body.role
    if body.is_active is not None:
        updates["is_active"] = int(body.is_active)
        if not body.is_active:
            db.revoke_all_user_sessions(user_id)

    if updates:
        db.update_user(user_id, **updates)
        db.audit("user_updated", user_id=admin["id"], username=admin["username"],
                 details={"target_user": user["username"], "changes": updates})

    return db.get_user_by_id(user_id)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(user_id: str, admin: dict = Depends(require_admin)):
    """Soft-deactivate: never hard-delete user records."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate your own account")
    db.update_user(user_id, is_active=0)
    db.revoke_all_user_sessions(user_id)
    db.audit("user_deactivated", user_id=admin["id"], username=admin["username"],
             details={"target_user": user["username"]})


@router.post("/users/{user_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
async def unlock_user(user_id: str, admin: dict = Depends(require_admin)):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    db.update_user(user_id, failed_attempts=0, locked_until=None)
    db.audit("user_unlocked", user_id=admin["id"], username=admin["username"],
             details={"target_user": user["username"]})


@router.post("/users/{user_id}/reset-sessions", status_code=status.HTTP_204_NO_CONTENT)
async def reset_sessions(user_id: str, admin: dict = Depends(require_admin)):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    db.revoke_all_user_sessions(user_id)
    db.audit("sessions_reset", user_id=admin["id"], username=admin["username"],
             details={"target_user": user["username"]})


@router.get("/audit-log")
async def audit_log(limit: int = 200, _: dict = Depends(require_admin)):
    return db.get_audit_log(limit=limit)


@router.get("/audit-log/{user_id}")
async def audit_log_user(user_id: str, limit: int = 100, _: dict = Depends(require_admin)):
    return db.get_audit_log(limit=limit, user_id=user_id)
