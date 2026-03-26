"""Offline/online sync manager.

Monitors internet connectivity and processes the queue of sessions that were
optimized offline but haven't yet received Claude AI enhancement.

Design for future web deployment:
- Replace the connectivity check with a health-check against your own API
- Replace the direct Claude calls with requests to the FastAPI backend
- The queue mechanism (SQLite sync_status column) remains identical
"""

from __future__ import annotations

import threading
import time

import requests

from revizor_frank.config import (
    ANTHROPIC_API_KEY,
    CONNECTIVITY_TEST_URL,
    CONNECTIVITY_TIMEOUT,
    SYNC_CHECK_INTERVAL,
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

            # Mark as syncing
            db.update_session(session["id"], sync_status="syncing")

            general_cv = cv_optimizer.optimize_general(offline_cv)
            db.update_session(session["id"], ai_cv_general=general_cv)

            jd_cv = None
            if jd:
                jd_cv = cv_optimizer.optimize_jd_tailored(cv_data, jd, general_cv)
                db.update_session(session["id"], ai_cv_jd=jd_cv)

            from revizor_frank.core import cv_optimizer as opt
            linkedin = opt.generate_linkedin(cv_data, general_cv, jd)
            db.update_session(
                session["id"],
                linkedin_data=linkedin,
                sync_status="synced",
                ai_enhanced=1,
            )
            enhanced += 1
        except Exception:
            # Put back in queue on failure
            db.update_session(session["id"], sync_status="queued")
    return enhanced


class SyncWorker(threading.Thread):
    """Background thread that periodically checks connectivity and drains the queue."""

    def __init__(self):
        super().__init__(daemon=True, name="revizor-sync-worker")
        self._stop_event = threading.Event()
        self.last_status: bool = False
        self.sessions_enhanced: int = 0

    def run(self):
        while not self._stop_event.is_set():
            online = is_online()
            self.last_status = online
            if online:
                self.sessions_enhanced += _process_queue()
            self._stop_event.wait(SYNC_CHECK_INTERVAL)

    def stop(self):
        self._stop_event.set()


# Module-level singleton — started once per app session
_worker: SyncWorker | None = None


def start_sync_worker() -> SyncWorker:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = SyncWorker()
        _worker.start()
    return _worker


def get_sync_status() -> dict:
    """Return a dict with current sync state for display in the UI."""
    online = is_online()
    queued = len(db.list_unsynced_sessions())
    return {
        "online": online,
        "queued_sessions": queued,
        "worker_alive": _worker is not None and _worker.is_alive(),
    }
