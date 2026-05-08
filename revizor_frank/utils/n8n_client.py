"""Outbound n8n integration for ReviZoR FranK.

Fires webhook calls to the n8n instance when CV review jobs are created,
and provides the signature-verification helper used by the FastAPI callback
endpoint to authenticate inbound results from n8n.

Configuration (all via .env):
    N8N_WEBHOOK_URL      Full URL of the n8n webhook trigger node.
                         e.g. https://n8n.yourdomain.com/webhook/revizor-review
    N8N_CALLBACK_SECRET  Shared secret for HMAC-SHA256 request signing.
                         Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    APP_CALLBACK_URL     Base URL of the ReviZoR FastAPI server, used so n8n
                         knows where to POST its result.
                         e.g. https://yourdomain.com
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime

import requests

N8N_WEBHOOK_URL     = os.getenv("N8N_WEBHOOK_URL", "")
N8N_CALLBACK_SECRET = os.getenv("N8N_CALLBACK_SECRET", "")
APP_CALLBACK_URL    = os.getenv("APP_CALLBACK_URL", "http://localhost:8000")
N8N_TIMEOUT_SECS    = int(os.getenv("N8N_TIMEOUT_SECS", "10"))


def _sign(body: str | bytes, secret: str) -> str:
    if isinstance(body, str):
        body = body.encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def is_configured() -> bool:
    """Return True if n8n webhook URL is set in the environment."""
    return bool(N8N_WEBHOOK_URL.strip())


def send_for_review(
    session_id: str,
    original_cv: dict,
    optimized_cv: dict,
    original_text: str = "",
    optimized_text: str = "",
    actor: str = "system",
    job_id: str | None = None,
) -> str:
    """Send a CV comparison job to n8n.  Returns the job_id.

    The payload contains both the structured CVData dicts and the plain-text
    representations so n8n can use whichever is easier to process.

    Raises requests.HTTPError / requests.Timeout on failure — callers should
    catch and handle gracefully.
    """
    if not N8N_WEBHOOK_URL:
        raise ValueError(
            "N8N_WEBHOOK_URL is not set. "
            "Add it to your .env file to enable n8n integration."
        )

    job_id = job_id or str(uuid.uuid4())
    callback_url = f"{APP_CALLBACK_URL.rstrip('/')}/api/n8n/callback"

    payload = {
        "job_id":         job_id,
        "session_id":     session_id,
        "callback_url":   callback_url,
        "sent_at":        datetime.utcnow().isoformat(),
        "actor":          actor,
        "original_cv":    original_cv,
        "optimized_cv":   optimized_cv,
        "original_text":  original_text,
        "optimized_text": optimized_text,
    }
    body = json.dumps(payload, ensure_ascii=False)
    sig  = _sign(body, N8N_CALLBACK_SECRET) if N8N_CALLBACK_SECRET else ""

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if sig:
        headers["X-ReviZoR-Signature"] = sig
    headers["X-ReviZoR-Job"] = job_id

    resp = requests.post(
        N8N_WEBHOOK_URL,
        data=body.encode(),
        headers=headers,
        timeout=N8N_TIMEOUT_SECS,
    )
    resp.raise_for_status()
    return job_id


def verify_callback_signature(body: bytes, signature: str) -> bool:
    """Verify that an inbound callback was signed by n8n with the shared secret.

    Returns True when:
      - N8N_CALLBACK_SECRET is not configured (dev/test mode — no check)
      - The HMAC-SHA256 of body matches the provided signature
    Returns False when the signature is wrong (potential spoofing).
    """
    if not N8N_CALLBACK_SECRET:
        return True
    expected = _sign(body, N8N_CALLBACK_SECRET)
    return hmac.compare_digest(expected.lower(), signature.lower())
