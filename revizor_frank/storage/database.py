"""SQLite persistence layer for ReviZoR FranK.

Schema is forward-compatible: adding new columns is done via ALTER TABLE
so existing databases are never broken by upgrades.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from revizor_frank.config import DB_PATH


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS cv_sessions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    filename        TEXT,
    raw_text        TEXT,
    parsed_data     TEXT,       -- JSON: CVData
    offline_cv      TEXT,       -- JSON: rule-optimized CVData
    ai_cv_general   TEXT,       -- JSON: Claude general-ATS CVData
    ai_cv_jd        TEXT,       -- JSON: Claude JD-tailored CVData
    ats_report      TEXT,       -- JSON: ATSReport
    linkedin_data   TEXT,       -- JSON: LinkedInProfile
    job_description TEXT,
    template        TEXT        DEFAULT 'modern',
    sync_status     TEXT        DEFAULT 'local',   -- local | queued | synced
    ai_enhanced     INTEGER     DEFAULT 0
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_SESSIONS)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.utcnow().isoformat()


def _json(obj: Any) -> str | None:
    return json.dumps(obj) if obj is not None else None


def _load(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


# ── Public API ────────────────────────────────────────────────────────────────

def create_session(filename: str, raw_text: str) -> str:
    """Create a new CV session and return its ID."""
    session_id = str(uuid.uuid4())
    ts = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO cv_sessions (id, created_at, updated_at, filename, raw_text)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, ts, ts, filename, raw_text),
        )
    return session_id


def update_session(session_id: str, **fields) -> None:
    """Update arbitrary fields on a session."""
    json_fields = {
        "parsed_data", "offline_cv", "ai_cv_general",
        "ai_cv_jd", "ats_report", "linkedin_data",
    }
    setters = []
    values = []
    for key, val in fields.items():
        setters.append(f"{key} = ?")
        values.append(_json(val) if key in json_fields else val)
    values.append(_now())
    values.append(session_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE cv_sessions SET {', '.join(setters)}, updated_at = ? WHERE id = ?",
            values,
        )


def get_session(session_id: str) -> dict | None:
    """Return a session as a plain dict with JSON fields already parsed."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cv_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("parsed_data", "offline_cv", "ai_cv_general",
                "ai_cv_jd", "ats_report", "linkedin_data"):
        d[key] = _load(d.get(key))
    return d


def list_unsynced_sessions() -> list[dict]:
    """Return sessions that have been processed offline but not yet AI-enhanced."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cv_sessions WHERE sync_status = 'queued' ORDER BY created_at"
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for key in ("parsed_data", "offline_cv", "ai_cv_general",
                    "ai_cv_jd", "ats_report", "linkedin_data"):
            d[key] = _load(d.get(key))
        result.append(d)
    return result


def list_recent_sessions(limit: int = 20) -> list[dict]:
    """Return recent sessions for the history view."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, filename, sync_status, ai_enhanced, template "
            "FROM cv_sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
