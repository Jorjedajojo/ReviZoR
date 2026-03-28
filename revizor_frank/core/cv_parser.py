"""CV file parser — extracts raw text and structured CVData from uploaded files.

Supports:
  - PDF: pdfminer.six (text-based) → Claude vision API (image-based/designed PDFs)
  - DOCX: python-docx
  - TXT: plain UTF-8 / latin-1

All parsing is fully local except for the Claude vision fallback used only when
pdfminer and PyMuPDF both return fewer than 100 characters (image-based PDF).

CVData schema (TypedDict-style for reference):
{
    "name": str,
    "email": str,
    "phone": str,
    "location": str,
    "linkedin": str,
    "website": str,
    "summary": str,
    "experience": [{"title", "company", "location", "start_date", "end_date", "bullets": [str]}],
    "education":  [{"degree", "institution", "location", "year", "gpa", "honors"}],
    "skills":     {"categories": [{"name": str, "items": [str]}]},
    "certifications": [{"name", "issuer", "date"}],
    "languages":  [str],
    "projects":   [{"name", "description", "technologies": [str]}],
    "raw_text":   str,
}
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import BinaryIO

import anthropic


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf(file: BinaryIO, api_key: str = "") -> tuple[str, int, int]:
    """Extract text from a PDF. Returns (text, input_tokens, output_tokens).

    Three-step strategy:
    1. pdfminer.six  — fast, fully local, great for text-based PDFs
    2. PyMuPDF       — local fallback for PDFs pdfminer can't parse
    3. Claude vision — final fallback for image-based / designed PDFs that
                       contain no text layer (e.g. exported from Canva/Figma)
    Steps 1 and 2 are tried first; Claude vision is only called when both
    return fewer than 100 characters of meaningful text.
    """
    data = file.read()

    # ── Step 1: pdfminer.six ─────────────────────────────────────────────────
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        from pdfminer.layout import LAParams
        laparams = LAParams(line_margin=0.5, char_margin=2.0, word_margin=0.1)
        text = pdfminer_extract(io.BytesIO(data), laparams=laparams)
        if text and len(text.strip()) > 100:
            return text, 0, 0
    except Exception:
        pass

    # ── Step 2: PyMuPDF ──────────────────────────────────────────────────────
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text("text") for page in doc]
        doc.close()
        text = "\n".join(pages)
        if text and len(text.strip()) > 100:
            return text, 0, 0
    except Exception:
        pass

    # ── Step 3: Claude vision (image-based PDF) ───────────────────────────────
    # Both local extractors returned < 100 chars — this is an image-based PDF.
    # Notify the Streamlit UI so the user knows what's happening.
    try:
        import streamlit as _st
        _st.toast("📄 Image-based PDF detected — using Claude Vision to extract text…", icon="👁️")
    except Exception:
        pass  # not running inside Streamlit (e.g. unit tests)

    key = api_key or ""
    if not key:
        raise ValueError(
            "This CV is an image-based PDF (no text layer was found by pdfminer or PyMuPDF). "
            "An Anthropic API key is required to extract text via Claude vision. "
            "Please add ANTHROPIC_API_KEY to your Streamlit secrets."
        )

    b64 = base64.standard_b64encode(data).decode()
    client = anthropic.Anthropic(api_key=key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
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
                        "text": (
                            "Extract all text content from this CV/resume exactly as it appears. "
                            "Include every section, every line, every detail — contact information, "
                            "summary, work experience, education, skills, certifications, languages, "
                            "and any other sections present. Output plain text only, no markdown."
                        ),
                    },
                ],
            }],
        )
    except Exception as e:
        try:
            import streamlit as _st
            _st.error(f"Vision extraction failed: {e}")
        except Exception:
            pass
        raise

    in_tok  = response.usage.input_tokens  if response.usage else 0
    out_tok = response.usage.output_tokens if response.usage else 0
    return response.content[0].text, in_tok, out_tok


def extract_text_from_docx(file: BinaryIO) -> str:
    from docx import Document
    doc = Document(io.BytesIO(file.read()))
    parts = []
    for para in doc.paragraphs:
        parts.append(para.text)
    # Also grab table cells
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def extract_text_from_txt(file: BinaryIO) -> str:
    raw = file.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def extract_text(file: BinaryIO, filename: str, api_key: str = "") -> tuple[str, int, int]:
    """Extract raw text from any supported file. Returns (text, input_tokens, output_tokens)."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file, api_key=api_key)
    elif ext == ".docx":
        return extract_text_from_docx(file), 0, 0
    else:
        return extract_text_from_txt(file), 0, 0


# ── Regex helpers ─────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?"
    r"(?:\(?\d{2,4}\)?[\s\-.]?)?"
    r"\d{3,4}[\s\-.]?\d{3,4}"
)
_LINKEDIN_RE = re.compile(r"(?:linkedin\.com/in/|linkedin:\s*)([A-Za-z0-9\-]+)", re.I)
_URL_RE = re.compile(r"https?://[^\s]+")
_DATE_RE = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s,]+\d{4}"
    r"|"
    r"\d{1,2}/\d{4}"
    r"|"
    r"\d{4}",
    re.I,
)

# Section heading detection — covers common CV heading variations.
# Trailing :, -, _, – and decorative fill characters are stripped.
# \s+ inside multi-word headings tolerates extra whitespace from PDF layout.
_SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("summary", re.compile(
        r"^\s*(summary|profile|objective|about\s+me|professional\s+summary|"
        r"career\s+objective|career\s+summary|personal\s+statement|"
        r"executive\s+summary)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("experience", re.compile(
        r"^\s*(experience|work\s+experience|employment|work\s+history|"
        r"career\s+history|professional\s+experience|employment\s+history|"
        r"career\s+experience|relevant\s+experience)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("education", re.compile(
        r"^\s*(education|academic|qualifications|academic\s+background|"
        r"education\s+[&and]+\s+training|educational\s+background|"
        r"academic\s+qualifications)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("skills", re.compile(
        r"^\s*(skills|technical\s+skills|core\s+competencies|competencies|"
        r"expertise|key\s+skills|skills\s+[&and]+\s+competencies|"
        r"skill\s+set|areas\s+of\s+expertise)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("certifications", re.compile(
        r"^\s*(certifications?|licenses?|credentials|accreditations?|"
        r"courses?|training|professional\s+development|"
        r"certificates?\s+[&and]+\s+licenses?)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("languages", re.compile(
        r"^\s*(languages?|language\s+skills|linguistic\s+skills)\s*[:\-–_─]*\s*$",
        re.I | re.M)),
    ("projects", re.compile(
        r"^\s*(projects?|personal\s+projects?|key\s+projects?|"
        r"selected\s+projects?|notable\s+projects?)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("publications", re.compile(
        r"^\s*(publications?|papers?|research|research\s+[&and]+\s+publications?)\s*[:\-–_─]*\s*$",
        re.I | re.M)),
    ("awards", re.compile(
        r"^\s*(awards?|honors?|achievements?|recognitions?|"
        r"awards?\s+[&and]+\s+honors?)\s*[:\-–_─]*\s*$", re.I | re.M)),
    ("volunteer", re.compile(
        r"^\s*(volunteer|volunteering|community|civic|"
        r"volunteer\s+experience)\s*[:\-–_─]*\s*$", re.I | re.M)),
]


# ── Section splitter ──────────────────────────────────────────────────────────

def _split_into_sections(text: str) -> dict[str, str]:
    """Split raw CV text into named sections."""
    lines = text.splitlines()
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    for line in lines:
        matched = False
        for section_name, pattern in _SECTION_PATTERNS:
            if pattern.match(line):
                current = section_name
                sections.setdefault(current, [])
                matched = True
                break
        if not matched:
            sections.setdefault(current, []).append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ── Contact extraction ────────────────────────────────────────────────────────

def _extract_contact(header_text: str) -> dict:
    lines = [l.strip() for l in header_text.splitlines() if l.strip()]

    email = ""
    em = _EMAIL_RE.search(header_text)
    if em:
        email = em.group(0)

    phone = ""
    ph = _PHONE_RE.search(header_text)
    if ph:
        phone = ph.group(0).strip()

    linkedin = ""
    li = _LINKEDIN_RE.search(header_text)
    if li:
        linkedin = f"linkedin.com/in/{li.group(1)}"

    website = ""
    for url in _URL_RE.finditer(header_text):
        u = url.group(0)
        if "linkedin" not in u.lower():
            website = u
            break

    # Name heuristic: longest line in first 5 lines that isn't contact info
    name = ""
    contact_tokens = {email, phone, linkedin, website}
    for line in lines[:5]:
        if line and not any(tok in line for tok in contact_tokens if tok):
            if not _EMAIL_RE.search(line) and not _PHONE_RE.search(line):
                if len(line) > len(name):
                    name = line

    # Location: look for "City, State/Country" pattern
    location = ""
    loc_re = re.compile(r"[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)+")
    loc_m = loc_re.search(header_text)
    if loc_m:
        location = loc_m.group(0)

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "location": location,
        "linkedin": linkedin,
        "website": website,
    }


# ── Experience parser ─────────────────────────────────────────────────────────

def _parse_experience(text: str) -> list[dict]:
    if not text:
        return []
    entries = []
    # Split on blank lines or date-like patterns indicating new entry
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        title, company, location, start_date, end_date = "", "", "", "", ""
        bullets = []

        for line in lines:
            if line.startswith(("•", "-", "–", "*", "·")):
                bullets.append(re.sub(r"^[•\-–*·]\s*", "", line))
                continue
            # Try to extract dates
            dates = _DATE_RE.findall(line)
            if dates and (len(dates) >= 2 or "present" in line.lower() or "current" in line.lower()):
                start_date = dates[0] if dates else ""
                end_date = dates[1] if len(dates) > 1 else ("Present" if "present" in line.lower() else "")
                # remainder might be title/company
                remainder = _DATE_RE.sub("", line).strip(" –-|·")
                if remainder and not title:
                    parts = re.split(r"[|·,]", remainder)
                    title = parts[0].strip() if parts else remainder
                    company = parts[1].strip() if len(parts) > 1 else ""
                continue
            if not title:
                title = line
            elif not company:
                company = line
            elif not location:
                # Simple location heuristic
                if any(c.isalpha() for c in line) and len(line) < 50:
                    location = line

        if title or bullets:
            entries.append({
                "title": title,
                "company": company,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "bullets": bullets,
            })
    return entries


# ── Education parser ──────────────────────────────────────────────────────────

def _parse_education(text: str) -> list[dict]:
    if not text:
        return []
    entries = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        degree, institution, location, year, gpa, honors = "", "", "", "", "", ""
        for line in lines:
            dates = _DATE_RE.findall(line)
            if dates:
                year = dates[-1]
            if re.search(r"\b(bachelor|master|phd|mba|b\.s|m\.s|b\.a|m\.a|bsc|msc|md|jd)\b", line, re.I):
                degree = line
            elif re.search(r"\b(university|college|institute|school|academy)\b", line, re.I):
                institution = line
            elif re.search(r"\bgpa\b", line, re.I):
                gpa = line
            elif re.search(r"\b(honor|cum laude|distinction)\b", line, re.I):
                honors = line
        if degree or institution:
            entries.append({
                "degree": degree,
                "institution": institution,
                "location": location,
                "year": year,
                "gpa": gpa,
                "honors": honors,
            })
    return entries


# ── Skills parser ─────────────────────────────────────────────────────────────

def _parse_skills(text: str) -> dict:
    if not text:
        return {"categories": [{"name": "Skills", "items": []}]}
    categories = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        # If first line looks like a category label (short, no punctuation at end)
        if len(lines[0]) < 40 and not lines[0].endswith((".", ",", ";")):
            cat_name = lines[0].rstrip(":")
            items_text = " ".join(lines[1:])
        else:
            cat_name = "Skills"
            items_text = " ".join(lines)
        # Split items by comma, pipe, semicolon, or bullet
        items = [
            i.strip(" •-–*·")
            for i in re.split(r"[,|;•·\n]", items_text)
            if i.strip(" •-–*·")
        ]
        if items:
            categories.append({"name": cat_name, "items": items})
    return {"categories": categories if categories else [{"name": "Skills", "items": []}]}


# ── Certifications parser ─────────────────────────────────────────────────────

def _parse_certifications(text: str) -> list[dict]:
    if not text:
        return []
    certs = []
    for line in text.splitlines():
        line = line.strip(" •-–*·").strip()
        if not line:
            continue
        dates = _DATE_RE.findall(line)
        date = dates[-1] if dates else ""
        name = _DATE_RE.sub("", line).strip(" –-|·,")
        parts = re.split(r"[|,·]", name)
        certs.append({
            "name": parts[0].strip(),
            "issuer": parts[1].strip() if len(parts) > 1 else "",
            "date": date,
        })
    return certs


# ── Languages parser ──────────────────────────────────────────────────────────

def _parse_languages(text: str) -> list[str]:
    if not text:
        return []
    langs = []
    for item in re.split(r"[,|;\n•]", text):
        item = item.strip(" •-–*·").strip()
        if item:
            langs.append(item)
    return langs


# ── Projects parser ───────────────────────────────────────────────────────────

def _parse_projects(text: str) -> list[dict]:
    if not text:
        return []
    projects = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        description = " ".join(lines[1:]) if len(lines) > 1 else ""
        # Extract technologies from parentheses or tech keywords
        tech_match = re.findall(r"\(([^)]+)\)", description)
        technologies = []
        for t in tech_match:
            technologies.extend([x.strip() for x in t.split(",")])
        projects.append({"name": name, "description": description, "technologies": technologies})
    return projects


# ── Main parse function ───────────────────────────────────────────────────────

def parse_cv(file: BinaryIO, filename: str, api_key: str = "") -> tuple[dict, int, int]:
    """Parse an uploaded CV file. Returns (CVData dict, input_tokens, output_tokens).

    input_tokens / output_tokens are non-zero only when a Claude vision call was
    required to extract text from an image-based PDF (no text layer).
    """
    raw_text, in_tok, out_tok = extract_text(file, filename, api_key=api_key)
    sections = _split_into_sections(raw_text)

    contact = _extract_contact(sections.get("header", ""))

    cv_data: dict = {
        **contact,
        "summary":        sections.get("summary", "").strip(),
        "experience":     _parse_experience(sections.get("experience", "")),
        "education":      _parse_education(sections.get("education", "")),
        "skills":         _parse_skills(sections.get("skills", "")),
        "certifications": _parse_certifications(sections.get("certifications", "")),
        "languages":      _parse_languages(sections.get("languages", "")),
        "projects":       _parse_projects(sections.get("projects", "")),
        "raw_text":       raw_text,
    }
    return cv_data, in_tok, out_tok
