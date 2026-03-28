"""Certificate field extraction via Claude API.

For PDF certificates: text extracted by pdfminer.six → Claude text call.
For image certificates (JPG/PNG): base64 → Claude vision call.

Each function returns (cert_dict, input_tokens, output_tokens).
cert_dict keys: name, issuer, date, credential_id
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import anthropic

from revizor_frank.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

_CERT_SCHEMA = {
    "name": "string — full certificate/course name",
    "issuer": "string — issuing organisation or platform (e.g. Coursera, AWS, PMI)",
    "date": "string — issue date formatted as Mon YYYY (e.g. Jan 2023), or year only",
    "credential_id": "string — certificate/credential ID number if visible, else empty string",
}

_CERT_PROMPT = (
    "Extract certificate information from the content below.\n\n"
    "Return ONLY a valid JSON object — no markdown, no commentary:\n"
    f"{json.dumps(_CERT_SCHEMA, indent=2)}"
)


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _empty_cert() -> dict:
    return {"name": "", "issuer": "", "date": "", "credential_id": ""}


# ── PDF certificate ───────────────────────────────────────────────────────────

def extract_from_pdf_bytes(pdf_bytes: bytes) -> tuple[dict, int, int]:
    """Extract cert fields from a PDF certificate.

    Two-step strategy:
    1. pdfminer.six extracts text → Claude text call (text-based PDFs)
    2. If pdfminer returns < 100 chars, send PDF as document to Claude vision
       (image-based / scanned certificates with no text layer)
    """
    text = ""
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        text = pdfminer_extract(io.BytesIO(pdf_bytes))
    except Exception:
        pass

    client = _get_client()

    # ── Text-based certificate ────────────────────────────────────────────────
    if text and len(text.strip()) > 100:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": f"{_CERT_PROMPT}\n\nCERTIFICATE TEXT:\n{text[:4000]}",
            }],
        )
        in_tok  = response.usage.input_tokens  if response.usage else 0
        out_tok = response.usage.output_tokens if response.usage else 0
        try:
            result = _extract_json(response.content[0].text)
        except Exception:
            result = _empty_cert()
        return result, in_tok, out_tok

    # ── Image-based certificate — send PDF directly via Claude vision ─────────
    b64 = base64.standard_b64encode(pdf_bytes).decode()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": _CERT_PROMPT,
                },
            ],
        }],
    )
    in_tok  = response.usage.input_tokens  if response.usage else 0
    out_tok = response.usage.output_tokens if response.usage else 0
    try:
        result = _extract_json(response.content[0].text)
    except Exception:
        result = _empty_cert()
    return result, in_tok, out_tok


# ── Image certificate ─────────────────────────────────────────────────────────

def extract_from_image_bytes(image_bytes: bytes, media_type: str) -> tuple[dict, int, int]:
    """Extract cert fields from a certificate image using Claude vision."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    client = _get_client()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": _CERT_PROMPT,
                },
            ],
        }],
    )
    in_tok = response.usage.input_tokens if response.usage else 0
    out_tok = response.usage.output_tokens if response.usage else 0
    try:
        result = _extract_json(response.content[0].text)
    except Exception:
        result = _empty_cert()
    return result, in_tok, out_tok


# ── Router ────────────────────────────────────────────────────────────────────

def extract_certificate(file_bytes: bytes, filename: str) -> tuple[dict, int, int]:
    """Route to PDF or image extraction based on file extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_from_pdf_bytes(file_bytes)
    elif ext in (".jpg", ".jpeg"):
        return extract_from_image_bytes(file_bytes, "image/jpeg")
    elif ext == ".png":
        return extract_from_image_bytes(file_bytes, "image/png")
    else:
        # Unknown type: return a stub with filename as name
        return {"name": Path(filename).stem, "issuer": "", "date": "", "credential_id": ""}, 0, 0
