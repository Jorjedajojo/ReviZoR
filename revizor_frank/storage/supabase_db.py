"""Supabase PostgreSQL storage for ReviZoR FranK.

Table schema (run once in your Supabase SQL editor):

    CREATE TABLE cv_runs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ DEFAULT NOW(),
      original_cv_text TEXT,
      revised_cv_text TEXT,
      linkedin_output JSONB,
      tier VARCHAR(20),
      price_usd DECIMAL(10,2),
      coupon_code VARCHAR(100),
      input_tokens INTEGER DEFAULT 0,
      output_tokens INTEGER DEFAULT 0,
      cost_usd DECIMAL(10,6),
      session_id TEXT,
      certificates JSONB,
      cert_input_tokens INTEGER DEFAULT 0,
      cert_output_tokens INTEGER DEFAULT 0,
      dob VARCHAR(50)
    );

    -- If upgrading an existing table, add the new columns:
    -- ALTER TABLE cv_runs ADD COLUMN IF NOT EXISTS certificates JSONB;
    -- ALTER TABLE cv_runs ADD COLUMN IF NOT EXISTS cert_input_tokens INTEGER DEFAULT 0;
    -- ALTER TABLE cv_runs ADD COLUMN IF NOT EXISTS cert_output_tokens INTEGER DEFAULT 0;
    -- ALTER TABLE cv_runs ADD COLUMN IF NOT EXISTS dob VARCHAR(50);
    -- ALTER TABLE cv_runs ADD COLUMN IF NOT EXISTS preferred_channel VARCHAR(50);

    CREATE TABLE cv_owner_questions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      session_id TEXT NOT NULL,
      token TEXT UNIQUE NOT NULL,
      questions JSONB NOT NULL DEFAULT '[]',
      answers JSONB,
      status VARCHAR(20) NOT NULL DEFAULT 'pending',
      created_at TIMESTAMPTZ DEFAULT NOW(),
      expires_at TIMESTAMPTZ,
      submitted_at TIMESTAMPTZ
    );
    -- If upgrading: CREATE TABLE cv_owner_questions (...) as above.

Pricing model (claude-sonnet-4-6):
  Input:  $3.00 per 1,000,000 tokens
  Output: $15.00 per 1,000,000 tokens
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Pricing constants ─────────────────────────────────────────────────────────
INPUT_TOKEN_COST_PER_M = 3.00   # USD per 1M input tokens
OUTPUT_TOKEN_COST_PER_M = 15.00  # USD per 1M output tokens


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Return total cost in USD for the given token counts."""
    return (input_tokens / 1_000_000) * INPUT_TOKEN_COST_PER_M + \
           (output_tokens / 1_000_000) * OUTPUT_TOKEN_COST_PER_M


# ── Client initialization ─────────────────────────────────────────────────────

def _get_client():
    """Return a Supabase client, or None if credentials are not configured."""
    try:
        from supabase import create_client, Client  # type: ignore
    except ImportError:
        logger.warning("supabase package not installed; Supabase storage disabled.")
        return None

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        logger.debug("SUPABASE_URL or SUPABASE_ANON_KEY not set; Supabase storage disabled.")
        return None

    try:
        return create_client(url, key)
    except Exception as exc:
        logger.error("Failed to create Supabase client: %s", exc)
        return None


# ── Write operations ──────────────────────────────────────────────────────────

def save_cv_run(
    *,
    session_id: str,
    original_cv_text: str,
    revised_cv_text: str,
    linkedin_output: Optional[dict],
    tier: str,
    price_usd: float,
    coupon_code: str,
    input_tokens: int,
    output_tokens: int,
    certificates: Optional[list] = None,
    cert_input_tokens: int = 0,
    cert_output_tokens: int = 0,
    dob: str = "",
) -> Optional[str]:
    """Save a completed CV run to Supabase.

    Returns the new row UUID on success, or None on failure / missing config.
    """
    client = _get_client()
    if client is None:
        return None

    cost = calculate_cost(input_tokens + cert_input_tokens, output_tokens + cert_output_tokens)

    row = {
        "session_id": session_id,
        "original_cv_text": original_cv_text,
        "revised_cv_text": revised_cv_text,
        "linkedin_output": linkedin_output,
        "tier": tier,
        "price_usd": price_usd,
        "coupon_code": coupon_code or None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "certificates": certificates or None,
        "cert_input_tokens": cert_input_tokens,
        "cert_output_tokens": cert_output_tokens,
        "dob": dob or None,
    }

    try:
        result = client.table("cv_runs").insert(row).execute()
        if result.data:
            return result.data[0].get("id")
    except Exception as exc:
        logger.error("Supabase insert failed: %s", exc)

    return None


# ── Read operations ───────────────────────────────────────────────────────────

def get_monthly_runs(year: int, month: int) -> list[dict]:
    """Return all cv_run rows for the given year/month (UTC).

    Each row includes: created_at, tier, price_usd, cost_usd,
    input_tokens, output_tokens, coupon_code, session_id.
    """
    client = _get_client()
    if client is None:
        return []

    # ISO date range for the month
    start = f"{year:04d}-{month:02d}-01T00:00:00+00:00"
    if month == 12:
        end = f"{year + 1:04d}-01-01T00:00:00+00:00"
    else:
        end = f"{year:04d}-{month + 1:02d}-01T00:00:00+00:00"

    try:
        result = (
            client.table("cv_runs")
            .select("id, created_at, tier, price_usd, cost_usd, input_tokens, output_tokens, coupon_code, session_id")
            .gte("created_at", start)
            .lt("created_at", end)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.error("Supabase monthly query failed: %s", exc)
        return []


def get_coupon_stats() -> list[dict]:
    """Return aggregated coupon usage stats.

    Returns list of {coupon_code, uses, total_revenue_usd, total_cost_usd}.
    """
    client = _get_client()
    if client is None:
        return []

    try:
        result = (
            client.table("cv_runs")
            .select("coupon_code, price_usd, cost_usd")
            .not_.is_("coupon_code", "null")
            .execute()
        )
        rows = result.data or []
    except Exception as exc:
        logger.error("Supabase coupon query failed: %s", exc)
        return []

    # Aggregate in Python (Supabase free tier has limited GROUP BY via RPC)
    stats: dict[str, dict] = {}
    for row in rows:
        code = row.get("coupon_code", "")
        if not code:
            continue
        if code not in stats:
            stats[code] = {"coupon_code": code, "uses": 0, "total_revenue_usd": 0.0, "total_cost_usd": 0.0}
        stats[code]["uses"] += 1
        stats[code]["total_revenue_usd"] += float(row.get("price_usd") or 0)
        stats[code]["total_cost_usd"] += float(row.get("cost_usd") or 0)

    return sorted(stats.values(), key=lambda x: x["uses"], reverse=True)


def get_all_runs_for_export() -> list[dict]:
    """Return all cv_run rows for CSV export (admin use)."""
    client = _get_client()
    if client is None:
        return []

    try:
        result = (
            client.table("cv_runs")
            .select("id, created_at, tier, price_usd, coupon_code, input_tokens, output_tokens, cost_usd, session_id")
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.error("Supabase export query failed: %s", exc)
        return []


# ── CV owner questions ────────────────────────────────────────────────────────

def save_owner_questions(
    *,
    session_id: str,
    token: str,
    questions: list[dict],
    expires_at: str,
) -> bool:
    """Store a set of questions for the CV owner. Returns True on success."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.table("cv_owner_questions").insert({
            "session_id": session_id,
            "token": token,
            "questions": questions,
            "status": "pending",
            "expires_at": expires_at,
        }).execute()
        return True
    except Exception as exc:
        logger.error("save_owner_questions failed: %s", exc)
        return False


def get_owner_questions(token: str) -> Optional[dict]:
    """Fetch a cv_owner_questions row by token. Returns None if not found."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = (
            client.table("cv_owner_questions")
            .select("*")
            .eq("token", token)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.error("get_owner_questions failed: %s", exc)
        return None


def submit_owner_answers(token: str, answers: list[dict]) -> bool:
    """Store CV owner's answers and mark row as submitted."""
    client = _get_client()
    if client is None:
        return False
    try:
        now = datetime.now(timezone.utc).isoformat()
        client.table("cv_owner_questions").update({
            "answers": answers,
            "status": "submitted",
            "submitted_at": now,
            "expires_at": now,  # immediately invalidate the link
        }).eq("token", token).execute()
        return True
    except Exception as exc:
        logger.error("submit_owner_answers failed: %s", exc)
        return False


def get_submitted_answers(session_id: str) -> Optional[dict]:
    """Return the most recent submitted answers row for a co-worker session."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = (
            client.table("cv_owner_questions")
            .select("*")
            .eq("session_id", session_id)
            .eq("status", "submitted")
            .order("submitted_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.error("get_submitted_answers failed: %s", exc)
        return None


def get_pending_responses() -> list[dict]:
    """Return all cv_owner_questions rows that are not yet closed."""
    client = _get_client()
    if client is None:
        return []
    try:
        result = (
            client.table("cv_owner_questions")
            .select("id, session_id, token, questions, status, created_at, expires_at, submitted_at")
            .neq("status", "closed")
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.error("get_pending_responses failed: %s", exc)
        return []


def close_owner_questions(row_id: str) -> bool:
    """Mark a cv_owner_questions row as closed."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.table("cv_owner_questions").update(
            {"status": "closed"}
        ).eq("id", row_id).execute()
        return True
    except Exception as exc:
        logger.error("close_owner_questions failed: %s", exc)
        return False


def save_session(username: str, state: dict) -> bool:
    """Upsert session state for a user in saved_sessions table."""
    client = _get_client()
    if client is None:
        return False
    try:
        import json as _json
        from datetime import datetime, timezone

        def _serializable(v):
            try:
                _json.dumps(v)
                return True
            except (TypeError, ValueError):
                return False

        payload = {
            "username": username,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stage": state.get("stage"),
            "filename": state.get("filename"),
            "parsed_cv": state.get("parsed_cv") if _serializable(state.get("parsed_cv")) else None,
            "ai_cv_general": state.get("ai_cv_general") if _serializable(state.get("ai_cv_general")) else None,
            "ai_cv_jd": state.get("ai_cv_jd") if _serializable(state.get("ai_cv_jd")) else None,
            "offline_cv": state.get("offline_cv") if _serializable(state.get("offline_cv")) else None,
            "linkedin_data": state.get("linkedin_data") if _serializable(state.get("linkedin_data")) else None,
            "job_description": state.get("job_description"),
            "service_tier": state.get("service_tier"),
            "selected_template": state.get("selected_template"),
            "template_color": state.get("template_color"),
            "ats_report": state.get("ats_report") if _serializable(state.get("ats_report")) else None,
            "missing_fields": state.get("missing_fields"),
            "session_id": str(state.get("session_id") or ""),
        }
        client.table("saved_sessions").upsert(
            payload, on_conflict="username"
        ).execute()
        return True
    except Exception as e:
        logger.warning("save_session failed: %s", e)
        return False


def load_session(username: str) -> dict | None:
    """Load the most recent saved session for a user."""
    client = _get_client()
    if client is None:
        return None
    try:
        r = (
            client.table("saved_sessions")
            .select("*")
            .eq("username", username)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]
        return None
    except Exception as e:
        logger.warning("load_session failed: %s", e)
        return None


def get_incomplete_sessions() -> list[dict]:
    """Return saved_sessions rows where missing_fields is a non-empty list."""
    client = _get_client()
    if client is None:
        return []
    try:
        r = (
            client.table("saved_sessions")
            .select("username, stage, filename, missing_fields, updated_at, session_id")
            .order("updated_at", desc=True)
            .execute()
        )
        return [
            row for row in (r.data or [])
            if row.get("missing_fields")  # non-null and non-empty list
        ]
    except Exception as e:
        logger.warning("get_incomplete_sessions failed: %s", e)
        return []


def update_preferred_channel(session_id: str, channel: str) -> None:
    """Record the co-worker's preferred share channel on the cv_runs row."""
    client = _get_client()
    if client is None:
        return
    try:
        client.table("cv_runs").update(
            {"preferred_channel": channel}
        ).eq("session_id", session_id).execute()
    except Exception as exc:
        logger.error("update_preferred_channel failed: %s", exc)
