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
