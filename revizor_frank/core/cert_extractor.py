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
        return {"name": Path(filename).stem, "issuer": "", "date": "", "credential_id": ""}, 0, 0


# ── Document type detection ───────────────────────────────────────────────────

def detect_document_type(file_bytes: bytes, filename: str) -> tuple[str, int, int]:
    """Classify a document as 'CERTIFICATE' or 'CV'. Returns (type, in_tok, out_tok).

    Uses a minimal Claude call (max_tokens=10) to keep cost negligible.
    Text-based files are classified via text; images/image PDFs via vision.
    """
    ext = Path(filename).suffix.lower()
    client = _get_client()
    _CLASSIFY_PROMPT = (
        "Is this document a certificate/qualification/credential or a CV/resume? "
        "Reply with exactly one word: CERTIFICATE or CV"
    )

    # ── Extract text for text-based formats ───────────────────────────────────
    text = ""
    if ext == ".pdf":
        try:
            from pdfminer.high_level import extract_text as _pdfm
            text = _pdfm(io.BytesIO(file_bytes))
        except Exception:
            pass
    elif ext == ".docx":
        try:
            from docx import Document as _Doc
            doc = _Doc(io.BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            pass
    elif ext == ".txt":
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass

    # ── Text-based classification ─────────────────────────────────────────────
    if text and len(text.strip()) > 50:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": f"{_CLASSIFY_PROMPT}\n\n{text[:2000]}"}],
        )
    elif ext in (".jpg", ".jpeg", ".png"):
        media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        b64 = base64.standard_b64encode(file_bytes).decode()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                {"type": "text",  "text": _CLASSIFY_PROMPT},
            ]}],
        )
    elif ext == ".pdf":
        # Image-based PDF — use document vision
        b64 = base64.standard_b64encode(file_bytes).decode()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text",     "text": _CLASSIFY_PROMPT},
            ]}],
        )
    else:
        return "CERTIFICATE", 0, 0

    in_tok  = response.usage.input_tokens  if response.usage else 0
    out_tok = response.usage.output_tokens if response.usage else 0
    raw = response.content[0].text.strip().upper()
    doc_type = "CV" if "CV" in raw or "RESUME" in raw else "CERTIFICATE"
    return doc_type, in_tok, out_tok


# ── CV extraction from arbitrary document ─────────────────────────────────────

def extract_cv_data_from_file(
    file_bytes: bytes, filename: str, api_key: str = ""
) -> tuple[dict, int, int]:
    """Parse a CV/resume document and return (CVData dict, in_tok, out_tok).

    Delegates to cv_parser.parse_cv so all three extraction strategies
    (pdfminer → PyMuPDF → Claude vision) are available.
    """
    from revizor_frank.core.cv_parser import parse_cv
    return parse_cv(io.BytesIO(file_bytes), filename, api_key=api_key)


# ── CV data merge ─────────────────────────────────────────────────────────────

def merge_cv_data(base: dict, new: dict) -> dict:
    """Merge new CV data into base, adding only non-duplicate information.

    Deduplication rules:
    - experience: by (title.lower, company.lower)
    - education:  by (degree.lower, institution.lower)
    - skills:     by item.lower within matching categories; new categories added
    - certs:      by name.lower
    - languages:  by language.lower
    - projects:   by name.lower
    - scalar fields (name, email, …): fill only if empty in base
    """
    import copy
    merged = copy.deepcopy(base)

    # Scalar fields: fill blanks only
    for field in ("name", "email", "phone", "location", "linkedin", "website", "summary"):
        if not merged.get(field) and new.get(field):
            merged[field] = new[field]

    # Experience
    existing_exp = {
        (e.get("title", "").lower().strip(), e.get("company", "").lower().strip())
        for e in merged.get("experience", [])
    }
    for exp in new.get("experience", []):
        key = (exp.get("title", "").lower().strip(), exp.get("company", "").lower().strip())
        if key not in existing_exp:
            merged.setdefault("experience", []).append(exp)
            existing_exp.add(key)

    # Education
    existing_edu = {
        (e.get("degree", "").lower().strip(), e.get("institution", "").lower().strip())
        for e in merged.get("education", [])
    }
    for edu in new.get("education", []):
        key = (edu.get("degree", "").lower().strip(), edu.get("institution", "").lower().strip())
        if key not in existing_edu:
            merged.setdefault("education", []).append(edu)
            existing_edu.add(key)

    # Skills — merge by category, dedup items
    all_items_lower: set[str] = set()
    for cat in merged.get("skills", {}).get("categories", []):
        for item in cat.get("items", []):
            all_items_lower.add(item.lower().strip())

    for new_cat in new.get("skills", {}).get("categories", []):
        matched_cat = next(
            (c for c in merged.setdefault("skills", {}).setdefault("categories", [])
             if c.get("name", "").lower() == new_cat.get("name", "").lower()),
            None,
        )
        for item in new_cat.get("items", []):
            if item.lower().strip() not in all_items_lower:
                if matched_cat:
                    matched_cat.setdefault("items", []).append(item)
                else:
                    merged["skills"]["categories"].append(
                        {"name": new_cat["name"], "items": [item]}
                    )
                    matched_cat = merged["skills"]["categories"][-1]
                all_items_lower.add(item.lower().strip())

    # Certifications
    existing_certs = {c.get("name", "").lower().strip() for c in merged.get("certifications", [])}
    for cert in new.get("certifications", []):
        if cert.get("name", "").lower().strip() not in existing_certs:
            merged.setdefault("certifications", []).append(cert)
            existing_certs.add(cert.get("name", "").lower().strip())

    # Languages
    existing_langs = {lang.lower().strip() for lang in merged.get("languages", [])}
    for lang in new.get("languages", []):
        if lang.lower().strip() not in existing_langs:
            merged.setdefault("languages", []).append(lang)
            existing_langs.add(lang.lower().strip())

    # Projects
    existing_proj = {p.get("name", "").lower().strip() for p in merged.get("projects", [])}
    for proj in new.get("projects", []):
        if proj.get("name", "").lower().strip() not in existing_proj:
            merged.setdefault("projects", []).append(proj)
            existing_proj.add(proj.get("name", "").lower().strip())

    return merged
