"""FastAPI router — n8n integration endpoints.

Two endpoints:
  POST /api/n8n/callback   — n8n posts its CV review result here
  GET  /api/n8n/job/{id}   — Streamlit polls this to check job status

Authentication: HMAC-SHA256 signature in X-ReviZoR-Signature header.
If N8N_CALLBACK_SECRET is not set the signature check is skipped (dev mode).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/api/n8n", tags=["n8n"])


@router.post("/callback")
async def n8n_callback(request: Request):
    """Receive a CV review result from an n8n workflow.

    Expected JSON body:
    {
        "job_id":          "<uuid>",
        "session_id":      "<uuid>",
        "status":          "completed" | "failed",
        "reviewed_cv":     { ...CVData dict or null... },
        "changes_summary": "Plain-text summary of what was changed",
        "error":           "Error message if status=failed"
    }

    The signature header X-ReviZoR-Signature must match HMAC-SHA256(body, secret).
    """
    from revizor_frank.utils.n8n_client import verify_callback_signature
    from revizor_frank.storage import database as cv_db

    body = await request.body()
    sig  = request.headers.get("X-ReviZoR-Signature", "")

    if not verify_callback_signature(body, sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing signature. "
                   "Set N8N_CALLBACK_SECRET in both .env and your n8n workflow.",
        )

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Body is not valid JSON")

    job_id     = data.get("job_id")
    session_id = data.get("session_id")
    if not job_id or not session_id:
        raise HTTPException(status_code=400, detail="job_id and session_id are required")

    job_status      = data.get("status", "completed")
    reviewed_cv     = data.get("reviewed_cv")
    changes_summary = data.get("changes_summary", "")
    error           = data.get("error")

    cv_db.complete_n8n_job(
        job_id=job_id,
        session_id=session_id,
        status=job_status,
        reviewed_cv=reviewed_cv,
        changes_summary=changes_summary,
        result=data,
        error=error,
    )

    return {"ok": True, "job_id": job_id, "status": job_status}


@router.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Poll a specific n8n job by ID.  Used by the Streamlit session poller."""
    from revizor_frank.storage import database as cv_db

    job = cv_db.get_n8n_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Strip the full payload/result blobs from polling responses (keep it light)
    return {
        "job_id":          job["id"],
        "session_id":      job["session_id"],
        "status":          job["status"],
        "changes_summary": job.get("changes_summary", ""),
        "has_reviewed_cv": bool(job.get("reviewed_cv")),
        "completed_at":    job.get("completed_at"),
        "error":           job.get("error"),
    }


@router.get("/session/{session_id}/latest")
async def get_latest_job(session_id: str):
    """Return the latest n8n job for a session."""
    from revizor_frank.storage import database as cv_db

    job = cv_db.get_latest_n8n_job(session_id)
    if not job:
        return {"job_id": None, "status": "none"}
    return {
        "job_id":          job["id"],
        "status":          job["status"],
        "changes_summary": job.get("changes_summary", ""),
        "has_reviewed_cv": bool(job.get("reviewed_cv")),
        "completed_at":    job.get("completed_at"),
    }
