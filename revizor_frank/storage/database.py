"""SQLite persistence layer for ReviZoR FranK.

Schema is forward-compatible: new columns are added via ALTER TABLE so
existing databases are never broken by upgrades.  _migrate() is called on
every connection and is safe to run repeatedly.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
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

# New columns added in lifecycle update — applied via _migrate()
_LIFECYCLE_COLUMNS = [
    ("stage",            "TEXT    DEFAULT 'upload'"),
    ("lifecycle_status", "TEXT    DEFAULT 'in_progress'"),
    ("candidate_name",   "TEXT"),
    ("candidate_email",  "TEXT"),
    ("lead_time_days",   "INTEGER DEFAULT 3"),
    ("delivery_due_at",  "TEXT"),
    ("completed_at",     "TEXT"),
    ("notes",            "TEXT"),
    ("edited_cv",        "TEXT"),
    ("review_decisions", "TEXT"),
    ("service_tier",     "TEXT"),
    ("actor",            "TEXT"),
]

_CREATE_ACTION_LOG = """
CREATE TABLE IF NOT EXISTS cv_action_log (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    actor       TEXT,
    action      TEXT NOT NULL,
    detail      TEXT                        -- JSON
)
"""

LIFECYCLE_STATUSES = frozenset(
    {"in_progress", "awaiting_info", "in_delivery", "expired", "completed"}
)

# Fields that must be JSON-serialised when writing to / from SQLite
_JSON_FIELDS = frozenset({
    "parsed_data", "offline_cv", "ai_cv_general", "ai_cv_jd",
    "ats_report", "linkedin_data", "edited_cv", "review_decisions",
})


# ── Connection + migration ────────────────────────────────────────────────────

def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cv_sessions)").fetchall()}
    for col, defn in _LIFECYCLE_COLUMNS:
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE cv_sessions ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass  # column already exists (concurrent migration)
    conn.execute(_CREATE_ACTION_LOG)
    conn.commit()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_SESSIONS)
    _migrate(conn)
    return conn


def _now() -> str:
    return datetime.utcnow().isoformat()


def _id() -> str:
    return str(uuid.uuid4())


def _json(obj: Any) -> str | None:
    return json.dumps(obj) if obj is not None else None


def _load(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


# ── Original API (preserved) ──────────────────────────────────────────────────

def create_session(filename: str, raw_text: str) -> str:
    """Create a new CV session and return its ID."""
    session_id = _id()
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
    setters = []
    values = []
    for key, val in fields.items():
        setters.append(f"{key} = ?")
        values.append(_json(val) if key in _JSON_FIELDS else val)
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
    for key in _JSON_FIELDS:
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
        for key in _JSON_FIELDS:
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


# ── Full-state save ───────────────────────────────────────────────────────────

def save_full_session(
    session_id: str,
    *,
    stage: str | None = None,
    candidate_name: str | None = None,
    candidate_email: str | None = None,
    parsed_data: dict | None = None,
    offline_cv: dict | None = None,
    ai_cv_general: dict | None = None,
    ai_cv_jd: dict | None = None,
    ats_report: dict | None = None,
    linkedin_data: dict | None = None,
    edited_cv: dict | None = None,
    review_decisions: dict | None = None,
    job_description: str | None = None,
    template: str | None = None,
    service_tier: str | None = None,
    actor: str | None = None,
) -> None:
    """Persist all current pipeline state fields into the session row."""
    plain = {}
    if stage is not None:           plain["stage"]           = stage
    if candidate_name is not None:  plain["candidate_name"]  = candidate_name
    if candidate_email is not None: plain["candidate_email"] = candidate_email
    if job_description is not None: plain["job_description"] = job_description
    if template is not None:        plain["template"]        = template
    if service_tier is not None:    plain["service_tier"]    = service_tier
    if actor is not None:           plain["actor"]           = actor

    json_pairs = [
        ("parsed_data",     parsed_data),
        ("offline_cv",      offline_cv),
        ("ai_cv_general",   ai_cv_general),
        ("ai_cv_jd",        ai_cv_jd),
        ("ats_report",      ats_report),
        ("linkedin_data",   linkedin_data),
        ("edited_cv",       edited_cv),
        ("review_decisions", review_decisions),
    ]
    serialised = {k: json.dumps(v) for k, v in json_pairs if v is not None}

    all_fields = {**plain, **serialised}
    if not all_fields:
        return

    all_fields["updated_at"] = _now()
    setters = [f"{k} = ?" for k in all_fields]
    with _connect() as conn:
        conn.execute(
            f"UPDATE cv_sessions SET {', '.join(setters)} WHERE id = ?",
            [*all_fields.values(), session_id],
        )


def get_full_session(session_id: str) -> dict | None:
    """Return the full session row with all JSON fields parsed."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cv_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in _JSON_FIELDS:
        d[key] = _load(d.get(key))
    return d


# ── Lifecycle management ──────────────────────────────────────────────────────

def log_action(
    session_id: str,
    actor: str,
    action: str,
    detail: dict | None = None,
) -> None:
    """Append an entry to the audit log for this session."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO cv_action_log (id, session_id, timestamp, actor, action, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_id(), session_id, _now(), actor, action,
             json.dumps(detail) if detail else None),
        )


def get_action_log(session_id: str, limit: int = 100) -> list[dict]:
    """Return the audit log for a session, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cv_action_log WHERE session_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["detail"] = _load(d.get("detail"))
        result.append(d)
    return result


def update_lifecycle(
    session_id: str,
    status: str,
    actor: str = "system",
    detail: dict | None = None,
) -> None:
    """Update lifecycle_status and append to audit log."""
    if status not in LIFECYCLE_STATUSES:
        raise ValueError(f"Invalid lifecycle status: {status!r}")
    ts = _now()
    extra_sets = ["lifecycle_status = ?", "updated_at = ?"]
    extra_vals: list = [status, ts]
    if status == "completed":
        extra_sets.append("completed_at = ?")
        extra_vals.append(ts)
    extra_vals.append(session_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE cv_sessions SET {', '.join(extra_sets)} WHERE id = ?",
            extra_vals,
        )
    log_action(session_id, actor, "status_changed",
               {"new_status": status, **(detail or {})})


def set_delivery(
    session_id: str,
    lead_time_days: int,
    actor: str = "system",
) -> str:
    """Set a delivery deadline and move status to in_delivery. Returns due ISO string."""
    due = (datetime.utcnow() + timedelta(days=lead_time_days)).isoformat()
    ts = _now()
    with _connect() as conn:
        conn.execute(
            """UPDATE cv_sessions
               SET lead_time_days = ?, delivery_due_at = ?,
                   lifecycle_status = 'in_delivery', updated_at = ?
               WHERE id = ?""",
            (lead_time_days, due, ts, session_id),
        )
    log_action(session_id, actor, "delivery_set",
               {"lead_time_days": lead_time_days, "due": due})
    return due


def add_note(session_id: str, note: str, actor: str = "system") -> None:
    """Append / replace operator notes and log the action."""
    with _connect() as conn:
        conn.execute(
            "UPDATE cv_sessions SET notes = ?, updated_at = ? WHERE id = ?",
            (note, _now(), session_id),
        )
    log_action(session_id, actor, "note_added", {"preview": note[:120]})


def mark_info_requested(session_id: str, actor: str, channel: str = "") -> None:
    """Set status to awaiting_info and log the request."""
    update_lifecycle(session_id, "awaiting_info", actor,
                     {"channel": channel} if channel else None)


# ── Dashboard listing ─────────────────────────────────────────────────────────

def list_sessions_dashboard(limit: int = 500) -> list[dict]:
    """Return all sessions ordered by last update, auto-expiring overdue ones."""
    now = _now()
    with _connect() as conn:
        # Auto-expire: in_delivery past their deadline → expired
        conn.execute(
            """UPDATE cv_sessions
               SET lifecycle_status = 'expired', updated_at = ?
               WHERE lifecycle_status = 'in_delivery'
                 AND delivery_due_at IS NOT NULL
                 AND delivery_due_at <= ?""",
            (now, now),
        )
        rows = conn.execute(
            """SELECT id, created_at, updated_at, filename, stage,
                      lifecycle_status, candidate_name, candidate_email,
                      lead_time_days, delivery_due_at, completed_at,
                      notes, template, sync_status, ai_enhanced, service_tier
               FROM cv_sessions
               ORDER BY updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_counts() -> dict[str, int]:
    """Return count of sessions per lifecycle_status for the summary strip."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT lifecycle_status, COUNT(*) as n FROM cv_sessions GROUP BY lifecycle_status"
        ).fetchall()
    counts: dict[str, int] = {s: 0 for s in LIFECYCLE_STATUSES}
    for row in rows:
        counts[row["lifecycle_status"]] = row["n"]
    counts["total"] = sum(counts.values())
    return counts
