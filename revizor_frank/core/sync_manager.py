"""Offline/online sync manager.

Checks connectivity and processes the queue of sessions optimized offline
that haven't yet received Claude AI enhancement.

Called on-demand from the Streamlit UI — no background threads, which are
unsafe in Streamlit's execution model (one thread per script rerun).
"""

from __future__ import annotations

import requests

from revizor_frank.config import (
    ANTHROPIC_API_KEY,
    CONNECTIVITY_TEST_URL,
    CONNECTIVITY_TIMEOUT,
)
from revizor_frank.storage import database as db


def is_online() -> bool:
    """Return True if the Anthropic API is reachable and an API key is configured."""
    if not ANTHROPIC_API_KEY:
        return False
    try:
        resp = requests.head(CONNECTIVITY_TEST_URL, timeout=CONNECTIVITY_TIMEOUT)
        return resp.status_code < 500
    except Exception:
        return False


def _process_queue() -> int:
    """Process all queued sessions. Returns number of sessions enhanced."""
    from revizor_frank.core import cv_optimizer

    sessions = db.list_unsynced_sessions()
    enhanced = 0
    for session in sessions:
        try:
            cv_data = session.get("parsed_data") or {}
            offline_cv = session.get("offline_cv") or cv_data
            jd = session.get("job_description") or ""

            db.update_session(session["id"], sync_status="syncing")

            general_cv = cv_optimizer.optimize_general(offline_cv)
            db.update_session(session["id"], ai_cv_general=general_cv)

            if jd:
                jd_cv = cv_optimizer.optimize_jd_tailored(cv_data, jd, general_cv)
                db.update_session(session["id"], ai_cv_jd=jd_cv)

            linkedin, _, _ = cv_optimizer.generate_linkedin(cv_data, general_cv, jd)
            db.update_session(
                session["id"],
                linkedin_data=linkedin,
                sync_status="synced",
                ai_enhanced=1,
            )
            enhanced += 1
        except Exception:
            db.update_session(session["id"], sync_status="queued")
    return enhanced


def maybe_sync() -> dict:
    """Check connectivity and drain the queue if online. Safe to call from Streamlit.

    Returns a status dict for optional UI display.
    """
    online = is_online()
    enhanced = 0
    if online:
        enhanced = _process_queue()
    queued = len(db.list_unsynced_sessions())
    return {"online": online, "enhanced": enhanced, "queued_sessions": queued}


def get_sync_status() -> dict:
    """Return current sync state without triggering any processing."""
    online = is_online()
    queued = len(db.list_unsynced_sessions())
    return {"online": online, "queued_sessions": queued}
