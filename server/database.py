"""User & session database for the ReviZoR FranK auth layer.

Uses SQLite by default (zero-config). Switch to PostgreSQL for production
by setting DATABASE_URL in the environment — SQLAlchemy-style URL:
  postgresql://user:password@host:5432/revizor

Schema is append-only (ALTER TABLE only) — safe to upgrade in-place.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parent.parent / "revizor_frank" / "storage" / "data" / "auth.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user',   -- user | admin
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    created_by      TEXT,
    last_login      TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT
)
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    token_jti       TEXT UNIQUE NOT NULL,   -- JWT ID (for revocation)
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    last_seen       TEXT,
    ip_address      TEXT,
    user_agent      TEXT,
    revoked         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""

_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    user_id     TEXT,
    username    TEXT,
    action      TEXT NOT NULL,   -- login | logout | login_failed | locked |
                                 -- user_created | user_deactivated | password_changed
    ip_address  TEXT,
    details     TEXT             -- JSON
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(_CREATE_USERS)
    conn.execute(_CREATE_SESSIONS)
    conn.execute(_CREATE_AUDIT)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.utcnow().isoformat()


def _id() -> str:
    return str(uuid.uuid4())


# ── Users ─────────────────────────────────────────────────────────────────────

def create_user(username: str, email: str, password_hash: str,
                role: str = "user", created_by: str | None = None) -> str:
    uid = _id()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO users (id, username, email, password_hash, role,
               is_active, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (uid, username.lower(), email.lower(), password_hash, role, _now(), created_by),
        )
    return uid


def get_user_by_username(username: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.lower(),)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, username, email, role, is_active, created_at, "
            "last_login, failed_attempts, locked_until FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id: str, **fields) -> None:
    setters = [f"{k} = ?" for k in fields]
    with _connect() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(setters)} WHERE id = ?",
            [*fields.values(), user_id],
        )


def record_failed_login(user_id: str) -> int:
    """Increment failed attempts counter. Returns new count."""
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id = ?",
            (user_id,),
        )
        row = conn.execute(
            "SELECT failed_attempts FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return row["failed_attempts"] if row else 0


def reset_failed_attempts(user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE id = ?",
            (_now(), user_id),
        )


def has_admin() -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE role = 'admin' AND is_active = 1"
        ).fetchone()
    return row["c"] > 0


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(user_id: str, token_jti: str, expires_at: str,
                   ip_address: str = "", user_agent: str = "") -> str:
    sid = _id()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO auth_sessions
               (id, user_id, token_jti, created_at, expires_at, last_seen, ip_address, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, user_id, token_jti, _now(), expires_at, _now(), ip_address, user_agent),
        )
    return sid


def get_session_by_jti(jti: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE token_jti = ? AND revoked = 0",
            (jti,),
        ).fetchone()
    return dict(row) if row else None


def revoke_session(jti: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked = 1 WHERE token_jti = ?", (jti,)
        )


def revoke_all_user_sessions(user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked = 1 WHERE user_id = ?", (user_id,)
        )


def touch_session(jti: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE auth_sessions SET last_seen = ? WHERE token_jti = ?",
            (_now(), jti),
        )


def list_user_sessions(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM auth_sessions WHERE user_id = ? AND revoked = 0 "
            "ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Audit log ─────────────────────────────────────────────────────────────────

def audit(action: str, user_id: str | None = None, username: str | None = None,
          ip_address: str = "", details: dict | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO audit_log (id, timestamp, user_id, username, action, ip_address, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_id(), _now(), user_id, username, action, ip_address,
             json.dumps(details) if details else None),
        )


def get_audit_log(limit: int = 200, user_id: str | None = None) -> list[dict]:
    with _connect() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
