"""Pydantic models for auth request/response payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # seconds until access token expiry
    expires_at: str          # ISO datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        from revizor_frank_server.auth.security import validate_password_strength
        errors = validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


class UserPublic(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str
    last_login: str | None = None


class UserSession(BaseModel):
    id: str
    created_at: str
    expires_at: str
    last_seen: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class MeResponse(BaseModel):
    user: UserPublic
    sessions: list[UserSession]
    session_expires_at: str
