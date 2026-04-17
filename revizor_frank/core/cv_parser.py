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
    "dob": str,      # date of birth (optional)
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

from revizor_frank.core.errors import raise_rvz


# ── Required fields ───────────────────────────────────────────────────────────
# Fields that must be present for a CV to be considered complete.
# skills_core is checked via the nested skills["categories"] structure.
REQUIRED_FIELDS: list[str] = [
    "name",
    "email",
    "phones",
    "experience",
    "education",
    "skills_core",
]

_REQUIRED_FIELD_LABELS: dict[str, str] = {
    "name":       "Full name",
    "email":      "Email address",
    "phones":     "Phone number",
    "experience": "Work experience",
    "education":  "Education",
    "skills_core": "Core skills",
}


def check_required_fields(cv_data: dict) -> list[str]:
    """Return a list of human-readable labels for required fields that are missing or empty.

    Checks REQUIRED_FIELDS against the parsed CVData dict.
    skills_core is satisfied when at least one Core Competencies category has items.
    """
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        label = _REQUIRED_FIELD_LABELS.get(field, field)
        if field == "phones":
            phones = cv_data.get("phones") or []
            if isinstance(phones, str):
                phones = [p.strip() for p in phones.split("|") if p.strip()]
            if not phones:
                missing.append(label)
        elif field == "skills_core":
            # Satisfied if any category named "Core Competencies" (or similar) has items
            cats = cv_data.get("skills", {}).get("categories", [])
            has_core = any(
                cat.get("items")
                for cat in cats
                if "core" in cat.get("name", "").lower() or "competenc" in cat.get("name", "").lower()
            )
            if not has_core:
                missing.append(label)
        else:
            val = cv_data.get(field)
            # For list fields (experience, education), only flag if key is entirely
            # absent (None). An empty list [] means the field parsed but found nothing —
            # that is not the same as missing information.
            # For scalar fields (name, email), empty string IS a genuine missing value.
            if field in ("experience", "education"):
                if val is None:
                    missing.append(label)
            else:
                if not val:
                    missing.append(label)
    return missing


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf_with_layout(file_data: bytes) -> str:
    """Column-aware PDF text extraction using PyMuPDF blocks.

    Detects multi-column layouts geometrically and re-sorts blocks so that
    column-1 text appears before column-2 text, eliminating the interleaving
    that occurs when two-column CVs are read line-by-line.
    """
    import fitz
    doc = fitz.open(stream=file_data, filetype="pdf")
    all_text_parts: list[str] = []
    for page in doc:
        page_width = page.rect.width
        blocks = page.get_text("blocks")
        # block tuple: (x0, y0, x1, y1, text, block_no, block_type); type 0 = text
        text_blocks = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, block_no, block_type in blocks
            if block_type == 0 and text.strip()
        ]
        if not text_blocks:
            continue
        # Cluster x0 values to detect columns
        x0_vals = sorted(set(round(b[0] / 10) * 10 for b in text_blocks))
        gap_threshold = 0.15 * page_width
        col_starts = [x0_vals[0]]
        for i in range(1, len(x0_vals)):
            if x0_vals[i] - x0_vals[i - 1] > gap_threshold:
                col_starts.append(x0_vals[i])
        num_cols = len(col_starts)
        if num_cols >= 2:
            def get_col(x0: float) -> int:
                for i in range(len(col_starts) - 1, -1, -1):
                    if x0 >= col_starts[i] - gap_threshold * 0.5:
                        return i
                return 0
            columns: list[list[tuple]] = [[] for _ in range(num_cols)]
            for x0, y0, x1, y1, text in text_blocks:
                columns[get_col(x0)].append((y0, text))
            page_parts: list[str] = []
            for col in columns:
                col.sort(key=lambda t: t[0])
                page_parts.extend(t[1] for t in col)
        else:
            text_blocks.sort(key=lambda b: b[1])
            page_parts = [b[4] for b in text_blocks]
        all_text_parts.extend(page_parts)
    doc.close()
    result = "\n".join(all_text_parts)
    if len(result.strip()) < 100:
        raise ValueError("Layout extraction yielded insufficient text")
    try:
        import streamlit as _st
        _st.session_state["parse_diagnostics"] = {
            "method": "fitz_layout",
            "columns_detected": num_cols if text_blocks else 1,
        }
    except Exception:
        pass
    return result


def extract_text_from_pdf(file: BinaryIO, api_key: str = "") -> tuple[str, int, int]:
    """Extract text from a PDF. Returns (text, input_tokens, output_tokens).

    Three-step strategy:
    1. PyMuPDF layout-aware — column detection + geometric re-sort (best for multi-col CVs)
    2. pdfminer.six          — fast local fallback for PDFs that fitz can't parse well
    3. Claude vision         — final fallback for image-based / designed PDFs with no text layer
    """
    data = file.read()

    # ── Step 1: fitz layout-aware (column detection) ─────────────────────────
    try:
        text = extract_text_from_pdf_with_layout(data)
        if text and len(text.strip()) >= 100:
            return text, 0, 0
    except Exception:
        pass

    # ── Step 2: pdfminer.six ─────────────────────────────────────────────────
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        from pdfminer.layout import LAParams
        laparams = LAParams(line_margin=0.5, char_margin=2.0, word_margin=0.1)
        text = pdfminer_extract(io.BytesIO(data), laparams=laparams)
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
                            "This CV may be in Arabic or another non-Latin script — preserve all "
                            "characters and Arabic text exactly as written. "
                            "If the CV is in Arabic, extract Arabic section headings verbatim "
                            "(e.g. الخبرة، التعليم، المهارات، اللغات، الشهادات، خلاصة). "
                            "Include every section, every line, every detail — contact information, "
                            "summary, work experience, education, skills, certifications, and especially "
                            "the Languages section: list every language with its proficiency level exactly "
                            "as written (e.g. Arabic – Native, English – Fluent, German – Intermediate, "
                            "or العربية – اللغة الأم، الإنجليزية – طلاقة). "
                            "Include any other sections present. Output plain text only, no markdown."
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
    from docx.oxml.ns import qn

    doc = Document(io.BytesIO(file.read()))
    parts: list[str] = []

    def _para_text(para_el) -> str:
        return "".join(node.text or "" for node in para_el.iter(qn("w:t")))

    def _process(el) -> None:
        tag = el.tag
        if tag == qn("w:p"):
            parts.append(_para_text(el))
            # text boxes embedded in this paragraph
            for txbx in el.iter(qn("w:txbxContent")):
                for child in txbx.iterchildren():
                    _process(child)
        elif tag == qn("w:tbl"):
            for row in el.iter(qn("w:tr")):
                for cell in row.findall(f".//{qn('w:tc')}"):
                    cell_lines = [_para_text(p) for p in cell.iter(qn("w:p"))]
                    parts.append("\n".join(cell_lines))

    for child in doc.element.body.iterchildren():
        _process(child)

    text = "\n".join(parts)
    if len(text.strip()) < 50:
        raise_rvz("RVZ-P001", detail=f"Extracted only {len(text.strip())} chars from DOCX")
    return text


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
    r"(?:\+\d{1,3}[\s.\-]?)?"           # optional country code: +20, +44
    r"(?:\(?\d{2,4}\)?[\s.\-]?)?"       # optional area code: (012), 012
    r"\d{2,4}[\s.\-]?\d{3,4}"           # main block: 012 345 or 0123 4567
    r"(?:[\s.\-]?\d{3,4})?"             # optional trailing block
    r"(?:[\s.\-]?\d{3,4})?"             # optional further trailing block
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
_DOB_RE = re.compile(
    r"(?:date\s+of\s+birth|dob|born|birth\s+date|تاريخ[\s\u200c]*الميلاد|تاريخ[\s\u200c]*الولادة)"
    r"[\s:]*"
    r"(\d{1,2}[\s\/\-\.]+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[\s,]+\d{4}"
    r"|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}"
    r"|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})",
    re.I,
)

# Additional DOB patterns: compiled once, tried in order against full raw_text.
# Covers more label variants, numeric-first and word-first month formats.
_DOB_PATTERNS: list[re.Pattern] = [
    # "date of birth / dob / born / birth date : DD MonthName YYYY"
    re.compile(
        r"(?:date\s+of\s+birth|dob|born|birth\s+date|تاريخ\s*الميلاد)"
        r"\s*[:\-\u2013\u2014]?\s*"
        r"(\d{1,2}[\s\-/\.]\w+[\s\-/\.]\d{2,4})",
        re.I,
    ),
    # "date of birth / dob / born : DD/MM/YYYY or DD-MM-YYYY"
    re.compile(
        r"(?:date\s+of\s+birth|dob|born|birth\s+date|تاريخ\s*الميلاد)"
        r"\s*[:\-\u2013\u2014]?\s*"
        r"(\d{1,2}[\s\-/\.]\d{1,2}[\s\-/\.]\d{2,4})",
        re.I,
    ),
    # "date of birth / dob / born : MonthName DD, YYYY"
    re.compile(
        r"(?:date\s+of\s+birth|dob|born)"
        r"\s*[:\-\u2013\u2014]?\s*"
        r"(\w+\s+\d{1,2},?\s+\d{4})",
        re.I,
    ),
    # Bare _DOB_RE (same as above but with the full month-name set)
    _DOB_RE,
]
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


def _is_arabic(text: str) -> bool:
    """Return True if the text contains significant Arabic script."""
    arabic_chars = sum(1 for c in text if _ARABIC_RE.match(c))
    return arabic_chars > 10


def _is_likely_landline(number: str) -> bool:
    """Return True if the number looks like a landline and should be dropped.

    Rules (apply only when 2+ numbers found — single numbers are always kept):
    - Numbers with a leading + are international format → always keep (return False)
    - 9 or fewer digits total → treat as landline
    Egyptian landlines: 02xxxxxxxx (Cairo, 10 digits total) or 03xxxxxxxx (Alex).
    The 9-digit threshold is conservative; Egyptian mobiles are always 11 digits.
    """
    stripped = number.strip()
    if stripped.startswith("+"):
        return False
    digits = re.sub(r"\D", "", stripped)
    return len(digits) <= 9


def _is_arabic_dominant(text: str) -> bool:
    """Return True if >30% of non-whitespace characters are Arabic script."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return False
    arabic_count = sum(1 for c in chars if _ARABIC_RE.match(c))
    return arabic_count / len(chars) > 0.30


class NonCVDocumentError(ValueError):
    """Raised when the uploaded document is detected to be a non-CV (e.g. job offer)."""
    pass

# Section heading detection — covers common CV heading variations.
# Trailing :, -, _, – and decorative fill characters are stripped.
# \s+ inside multi-word headings tolerates extra whitespace from PDF layout.
_SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("personal_info", re.compile(
        r"^\s*(personal\s+information|personal\s+details|"
        r"بيانات\s*شخصية|معلومات\s*شخصية)\s*[:\-–_─]?\s*$",
        re.M | re.I)),
    ("summary", re.compile(
        r"^\s*(summary|profile|objective|about\s+me|professional\s+summary|"
        r"career\s+objective|career\s+summary|personal\s+statement|executive\s+summary|"
        r"introduction|"
        r"خلاصة|ملخص|الهدف|نبذة\s*شخصية|ملخص\s*مهني|الغرض|نبذة\s*تعريفية|"
        r"البيانات\s*الشخصية|المؤهلات\s*الشخصية)\s*:?\s*$",
        re.M | re.I)),
    ("experience", re.compile(
        r"^\s*(experience|work\s+experience|working\s+experience|employment|work\s+history|"
        r"career\s+history|professional\s+experience|professional\s+history|"
        r"employment\s+history|career\s+experience|relevant\s+experience|"
        r"الخبرة|الخبرات|الخبرة\s*المهنية|الخبرات\s*المهنية|تاريخ\s*العمل|المسيرة\s*المهنية|"
        r"خبرات\s*العمل|سجل\s*العمل)\s*:?\s*$",
        re.M | re.I)),
    ("education", re.compile(
        r"^\s*(education|academic|qualifications|academic\s+background|"
        r"academic\s+history|educational\s+qualifications|educational\s+background|"
        r"education\s+(?:&\s*)?and\s+training|academic\s+qualifications|"
        r"التعليم|المؤهلات|المؤهلات\s*الدراسية|الخلفية\s*الأكاديمية|التعليم\s*والتدريب)\s*:?\s*$",
        re.M | re.I)),
    ("skills", re.compile(
        r"^\s*(skills|technical\s+skills|core\s+competencies|competencies|"
        r"expertise|key\s+skills|skills\s+(?:&\s*)?and\s+competencies|skill\s+set|"
        r"areas\s+of\s+expertise|computer\s+skills|it\s+skills|hard\s+skills|"
        r"soft\s+skills|professional\s+skills|"
        r"المهارات|المهارات\s*الأساسية|المهارات\s*التقنية|الكفاءات|الكفاءات\s*الجوهرية)\s*:?\s*$",
        re.M | re.I)),
    ("certifications", re.compile(
        r"^\s*(certifications?|licenses?|credentials|accreditations?|"
        r"professional\s+development|certificates?\s+(?:&\s*)?and\s+licenses?|"
        r"الشهادات|الشهادات\s*المهنية|الاعتمادات)\s*:?\s*$",
        re.M | re.I)),
    ("training", re.compile(
        r"^\s*(training|professional\s+training|courses?\s+and\s+training|"
        r"training\s+and\s+development|training\s+and\s+certifications?|"
        r"courses?|الدورات|التدريب|الدورات\s*التدريبية)\s*:?\s*$",
        re.M | re.I)),
    ("languages", re.compile(
        r"^\s*(languages?|language\s+skills|linguistic\s+skills|"
        r"languages?\s+(?:&\s*)?and\s+communication|spoken\s+languages?|"
        r"language\s+proficiencies|language\s+abilities|"
        r"لغات|اللغات|المهارات\s*اللغوية)\s*:?\s*$",
        re.M | re.I)),
    ("projects", re.compile(
        r"^\s*(projects?|personal\s+projects?|key\s+projects?|"
        r"selected\s+projects?|notable\s+projects?|"
        r"المشاريع|المشاريع\s*الرئيسية)\s*:?\s*$",
        re.M | re.I)),
    ("publications", re.compile(
        r"^\s*(publications?|papers?|research|research\s+(?:&\s*)?and\s+publications?|"
        r"الأبحاث|المنشورات)\s*:?\s*$",
        re.M | re.I)),
    ("awards", re.compile(
        r"^\s*(awards?|honors?|achievements?|recognitions?|awards?\s+(?:&\s*)?and\s+honors?|"
        r"الجوائز|التكريمات|الإنجازات)\s*:?\s*$",
        re.M | re.I)),
    ("volunteer", re.compile(
        r"^\s*(volunteer|volunteering|community|civic|volunteer\s+experience|"
        r"التطوع|العمل\s*التطوعي)\s*:?\s*$",
        re.M | re.I)),
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

    # Collect all phone numbers; deduplicate by normalised digit sequence
    _seen_digits: set[str] = set()
    _all_phones: list[str] = []
    for _raw_ph in _PHONE_RE.findall(header_text):
        _p = _raw_ph.strip()
        if not _p:
            continue
        _digits = re.sub(r"\D", "", _p)
        if len(_digits) < 7 or len(_digits) > 15:
            continue
        if _digits not in _seen_digits:
            _seen_digits.add(_digits)
            _all_phones.append(_p)
    # Drop likely landlines only when 2+ numbers were found (keep single numbers always)
    if len(_all_phones) >= 2:
        _mobile_phones = [p for p in _all_phones if not _is_likely_landline(p)]
        phones = _mobile_phones if _mobile_phones else _all_phones
    else:
        phones = _all_phones
    phone = " | ".join(phones)   # joined string for backward compatibility

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

    # Name heuristic: longest suitable line in first 5 lines
    # Works for both Latin and Arabic names
    _SKIP_PREFIXES = (
        "address", "addr", "telephone", "tel", "mobile", "mob", "phone",
        "email", "e-mail", "fax", "website", "url", "linkedin",
        "date of birth", "nationality", "place of birth", "city", "country",
        "\u0627\u0644\u0639\u0646\u0648\u0627\u0646",  # العنوان
    )
    name = ""
    name_idx = -1  # set by priority pass so title extractor finds the right line
    contact_tokens = {email, phone, linkedin, website}

    # Priority pass: if the first non-contact, non-DOB line is all-caps
    # and 2–5 words, accept it immediately as the candidate name (title-cased).
    for _pi, _pline in enumerate(lines[:5]):
        if not _pline:
            continue
        if any(tok in _pline for tok in contact_tokens if tok):
            continue
        if _EMAIL_RE.search(_pline) or _PHONE_RE.search(_pline):
            continue
        if _DOB_RE.search(_pline):
            continue
        _plow = _pline.lower()
        if any(_plow.startswith(pfx) for pfx in _SKIP_PREFIXES):
            continue
        _pwords = _pline.split()
        if _pline.isupper() and 2 <= len(_pwords) <= 4:
            name = _pline.title()
            name_idx = _pi  # record position so title search starts from next line
        break  # only check the very first viable line

    # General fallback: longest suitable line (when priority pass found nothing)
    if not name:
        for line in lines[:5]:
            if not line:
                continue
            if any(tok in line for tok in contact_tokens if tok):
                continue
            if _EMAIL_RE.search(line) or _PHONE_RE.search(line):
                continue
            # Skip DOB lines
            if _DOB_RE.search(line):
                continue
            lower = line.lower()
            if any(lower.startswith(prefix) for prefix in _SKIP_PREFIXES):
                continue
            # Skip all-uppercase lines with 5+ words — these are headings not names
            if line.isupper() and len(line.split()) >= 5:
                continue
            if len(line) > len(name):
                name = line

    # Title: professional title on the line immediately below the candidate name,
    # before the contact block. Fallback: first non-empty, non-contact line after name.
    title = ""
    # name_idx may already be set by the all-caps priority pass above (where the
    # stored name is title-cased but lines[] still holds the original uppercase string).
    if name_idx < 0:
        name_idx = next((i for i, l in enumerate(lines[:8]) if l == name), -1)
    if name_idx >= 0:
        for candidate in lines[name_idx + 1: name_idx + 5]:
            c = candidate.strip()
            if not c:
                continue
            if _EMAIL_RE.search(c) or _PHONE_RE.search(c):
                continue
            if _DOB_RE.search(c):
                continue
            # Skip lines that are URLs
            if re.search(r"https?://|www\.", c, re.I):
                continue
            if any(c.lower().startswith(p) for p in _SKIP_PREFIXES):
                continue
            # Accept up to 12 words and 120 chars — enough for compound titles
            if len(c) <= 120 and 1 <= len(c.split()) <= 12:
                title = c
                break

    # Location: "City, State/Country" for Latin; skip for Arabic (too complex)
    location = ""
    if not _is_arabic(header_text):
        loc_re = re.compile(r"[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)+")
        loc_m = loc_re.search(header_text)
        if loc_m:
            location = loc_m.group(0)

    # DOB extraction
    dob = ""
    dob_m = _DOB_RE.search(header_text)
    if dob_m:
        dob = dob_m.group(1).strip()

    # Neighbourhood: explicit label, or first component of a 3-part address
    neighbourhood = ""
    _NEIGH_RE = re.compile(
        r"(?:neighbourhood|neighborhood|district|area|zone|حي|منطقة)\s*:?\s*([^\n,|]{2,40})",
        re.I,
    )
    neigh_m = _NEIGH_RE.search(header_text)
    if neigh_m:
        neighbourhood = neigh_m.group(1).strip()
    elif location:
        _loc_parts = [p.strip() for p in location.split(",")]
        if len(_loc_parts) >= 3:
            neighbourhood = _loc_parts[0]

    return {
        "name": name,
        "title": title,
        "email": email,
        "phones": phones,            # list — primary; one item per unique number
        "phone": phone,              # joined string — backward-compat for optimizer/templates
        "location": location,
        "neighbourhood": neighbourhood,
        "linkedin": linkedin,
        "website": website,
        "dob": dob,
    }


# ── Experience parser ─────────────────────────────────────────────────────────

def _parse_experience(text: str) -> list[dict]:
    if not text:
        return []

    _DATE_RANGE_RE = re.compile(
        r"((?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{4})"
        r"[\s.\-/]*(?:\d{2,4})?[\s]*(?:\u2013|-|to)[\s]*"
        r"(?:present|current|now|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{4})"
        r"[\s.\-/]*(?:\d{2,4})?)",
        re.I,
    )

    lines = text.splitlines()
    entries: list[dict] = []
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        date_match = _DATE_RANGE_RE.search(stripped)
        if date_match:
            if current:
                entries.append(current)
            dates = _DATE_RE.findall(stripped)
            start = dates[0] if dates else ""
            end = dates[1] if len(dates) > 1 else (
                "Present" if re.search(r"present|current|now", stripped, re.I) else ""
            )
            remainder = _DATE_RE.sub("", stripped)
            remainder = re.sub(r"\b(?:present|current|now)\b", "", remainder, flags=re.I)
            remainder = remainder.strip(" \u2013-|·,").strip()
            _rparts   = re.split(r"\s+-\s+", remainder, maxsplit=1)
            _title    = _rparts[0].strip() if _rparts else ""
            _company  = _rparts[1].strip() if len(_rparts) > 1 else ""
            current = {
                "title":      _title,
                "company":    _company,
                "location":   "",
                "start_date": start,
                "end_date":   end,
                "bullets":    [],
            }
            continue

        if current is None:
            continue

        if stripped[:1] in ("\u2022", "\uf0b7", "\u2023", "\u2219", "-", "\u2013", "*") or stripped.startswith("•"):
            bullet = re.sub(r"^[\u2022\uf0b7\u2023\u2219\u2013\u2014\-\*•]\s*", "", stripped).strip()
            if bullet and len(bullet) > 5:
                current["bullets"].append(bullet)

    if current:
        entries.append(current)

    return [e for e in entries if e["title"] or e["company"] or e["bullets"]]


# ── Education parser ──────────────────────────────────────────────────────────

def _parse_education(text: str) -> list[dict]:
    if not text:
        return []

    _DEGREE_KW_RE = re.compile(
        r"\b(bachelor|master|phd|mba|bsc|msc|diploma|ba|ma|md|jd)\b", re.I
    )
    _EDU_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    buckets: list[list[str]] = []
    for line in lines:
        if _DEGREE_KW_RE.search(line) or _EDU_YEAR_RE.search(line):
            buckets.append([line])
        elif buckets:
            buckets[-1].append(line)

    entries = []
    for bucket in buckets:
        if not bucket:
            continue
        primary = bucket[0]
        parts = re.split(r"\s+[-|]\s+", primary)
        degree = parts[0].strip() if parts else primary
        institution = parts[1].strip() if len(parts) > 1 else ""
        years = _EDU_YEAR_RE.findall(primary)
        year = years[-1] if years else ""
        degree = _EDU_YEAR_RE.sub("", degree).strip(" -|")
        institution = _EDU_YEAR_RE.sub("", institution).strip(" -|")
        gpa = ""
        honors = ""
        for extra in bucket[1:]:
            if re.search(r"\bgpa\b", extra, re.I):
                gpa = extra
            elif re.search(r"\b(honor|cum laude|distinction)\b", extra, re.I):
                honors = extra
            elif not institution:
                institution = extra
        if degree or institution:
            entries.append({
                "degree": degree,
                "institution": institution,
                "location": "",
                "year": year,
                "gpa": gpa,
                "honors": honors,
            })
    return entries


# ── Skills classifier ─────────────────────────────────────────────────────────

_CORE_SKILL_TOKENS: frozenset[str] = frozenset([
    "leadership", "management", "communication", "teamwork", "collaboration",
    "analytical", "analysis", "strategic", "planning", "problem solving",
    "problem-solving", "critical thinking", "presentation", "negotiation",
    "interpersonal", "time management", "organizational", "multitasking",
    "adaptability", "flexibility", "creativity", "innovation", "decision making",
    "customer service", "stakeholder", "training", "coaching", "mentoring",
    "report writing", "writing", "budgeting", "coordination", "facilitation",
    "conflict resolution", "emotional intelligence", "networking", "change management",
    "people management", "verbal", "written", "documentation", "relationship",
    "team building", "motivation", "empathy", "diplomacy", "cultural",
])
_TECHNICAL_SKILL_TOKENS: frozenset[str] = frozenset([
    "python", "java", "javascript", "typescript", "c++", "c#", "ruby", "php",
    "swift", "kotlin", "go", "rust", "scala", "r", "matlab", "perl", "bash", "shell",
    "sql", "html", "css", "xml", "json", "yaml", "react", "angular", "vue",
    "node.js", "nodejs", "django", "flask", "fastapi", "spring", "laravel",
    "aws", "azure", "gcp", "google cloud", "cloud", "docker", "kubernetes",
    "terraform", "ansible", "jenkins", "ci/cd", "devops", "linux", "unix",
    "git", "github", "gitlab", "excel", "powerpoint", "vba",
    "tableau", "power bi", "looker", "salesforce", "sap", "oracle", "dynamics",
    "jira", "confluence", "tensorflow", "pytorch", "scikit-learn", "keras",
    "pandas", "numpy", "machine learning", "deep learning", "nlp", "computer vision",
    "hadoop", "spark", "kafka", "databricks", "snowflake", "mongodb", "postgresql",
    "mysql", "redis", "elasticsearch", "photoshop", "illustrator", "figma",
    "autocad", "solidworks", "unity", "api", "microservices", "android", "ios",
    "flutter", "react native", "network", "cisco", "firewall", "vpn",
    "programming", "software", "database", "server", "backend", "frontend",
    "full stack", "fullstack", "infrastructure", "security", "testing", "qa",
    "automation", "data", "analytics", "bi", "erp", "crm",
])


def _classify_skill_item(item: str) -> str:
    """Return 'core' or 'technical' for a single skill string."""
    lower = item.lower()
    # Core takes priority — check it first to avoid false-technical matches
    if any(kw in lower for kw in _CORE_SKILL_TOKENS):
        return "core"
    # For technical: use word-boundary match for single-char tokens (e.g. "r")
    for kw in _TECHNICAL_SKILL_TOKENS:
        if len(kw) == 1:
            if re.search(r"\b" + re.escape(kw) + r"\b", lower):
                return "technical"
        else:
            if kw in lower:
                return "technical"
    # Heuristic: all-caps abbreviations or items with symbols look technical
    if re.search(r"\b[A-Z]{2,}\b", item) or re.search(r"[./+#\d]", item):
        return "technical"
    return "core"


def _split_into_core_technical(items: list[str]) -> dict:
    """Classify a flat skill list into Core and Technical Competencies."""
    core, technical = [], []
    for item in items:
        if _classify_skill_item(item) == "technical":
            technical.append(item)
        else:
            core.append(item)
    categories = []
    if technical:
        categories.append({"name": "Technical Competencies", "items": technical})
    if core:
        categories.append({"name": "Core Competencies", "items": core})
    return {"categories": categories or [{"name": "Skills", "items": items}]}


# ── Skills parser ─────────────────────────────────────────────────────────────

_GENERIC_SKILL_CAT = re.compile(r"^(skills?|competencies|expertise)$", re.I)


def _parse_skills(text: str) -> dict:
    if not text:
        return {"categories": [{"name": "Technical Competencies", "items": []},
                                {"name": "Core Competencies", "items": []}]}
    categories = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        # If first line looks like a category label (short, no punctuation at end,
        # and contains no commas or bullet separators — those mean it IS a skill list)
        if (len(lines[0]) < 50
                and not lines[0].endswith((".", ","))
                and "," not in lines[0]
                and not re.search(r"[•|;·]", lines[0])):
            cat_name = lines[0].rstrip(":").strip()
            items_text = ", ".join(lines[1:])
        else:
            cat_name = ""
            items_text = ", ".join(lines)
        # Split items by comma, pipe, semicolon, or bullet
        items = [
            i.strip(" •-–*·")
            for i in re.split(r"[,|;•·\n]", items_text)
            if i.strip(" •-–*·")
        ]
        if items:
            categories.append({"name": cat_name or "Skills", "items": items})

    if not categories:
        return {"categories": [{"name": "Technical Competencies", "items": []},
                                {"name": "Core Competencies", "items": []}]}

    # If there's a single generic "Skills" category, auto-classify into Core / Technical
    if len(categories) == 1 and _GENERIC_SKILL_CAT.match(categories[0]["name"]):
        return _split_into_core_technical(categories[0]["items"])

    # Also reclassify if category names match generic variations
    all_items = []
    all_generic = all(_GENERIC_SKILL_CAT.match(c["name"]) for c in categories)
    if all_generic:
        for cat in categories:
            all_items.extend(cat["items"])
        return _split_into_core_technical(all_items)

    return {"categories": categories}


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

# Common language names for fallback scan (lowercase)
_KNOWN_LANGUAGES = [
    "arabic", "english", "french", "german", "spanish", "italian", "portuguese",
    "chinese", "mandarin", "japanese", "korean", "russian", "dutch", "turkish",
    "persian", "farsi", "hindi", "urdu", "swahili", "polish", "swedish", "norwegian",
    "danish", "greek", "hebrew", "thai", "vietnamese", "indonesian", "malay",
    "romanian", "hungarian", "czech", "slovak", "bulgarian", "croatian", "serbian",
    "ukrainian", "catalan", "finnish", "latvian", "lithuanian", "estonian",
]
_PROFICIENCY_WORDS = [
    "native", "fluent", "intermediate", "advanced", "basic", "beginner",
    "mother tongue", "excellent", "very good", "good", "fair", "conversational",
    "professional", "business", "working", "elementary", "limited", "bilingual",
]


def _parse_languages(text: str) -> list[str]:
    if not text:
        return []
    langs = []
    for item in re.split(r"[,|;\n•]", text):
        item = item.strip(" •-–*·").strip()
        if item:
            langs.append(item)
    return langs


def _fallback_language_scan(raw_text: str) -> list[str]:
    """Scan raw CV text for language names when no language section was found."""
    found: list[str] = []
    seen: set[str] = set()
    text_lower = raw_text.lower()

    for lang in _KNOWN_LANGUAGES:
        if lang not in text_lower:
            continue
        # Capture up to 60 chars AFTER the language name to detect proficiency
        # (e.g. "Arabic – Native", "English: Fluent")
        pattern = rf"[^\n]{{0,60}}\b{re.escape(lang)}\b([^\n]{{0,60}})"
        for m in re.finditer(pattern, raw_text, re.I):
            norm = lang.lower()
            if norm in seen:
                break
            seen.add(norm)
            # Only look at text AFTER the language name for proficiency
            after = m.group(1).lower()
            prof = next(
                (p for p in _PROFICIENCY_WORDS if p in after),
                None,
            )
            if prof:
                found.append(f"{lang.title()} ({prof.title()})")
            # No proficiency word after → skip; do not add a bare language name
            break  # only capture each language once

    return found


# ── Document type classifier (job offer vs CV) ────────────────────────────────

def _classify_document(text: str, api_key: str) -> tuple[str, int, int]:
    """Return ('CV'|'OTHER', in_tok, out_tok).

    Heuristic-first: only calls Claude when the text is ambiguous.
    Returns 'CV' on any error to avoid blocking valid uploads.
    """
    if not text.strip():
        return "CV", 0, 0

    text_lower = text.lower()
    cv_indicators = sum(1 for w in [
        "experience", "education", "skills", "resume", "curriculum vitae",
        "الخبرة", "التعليم", "المهارات", "السيرة الذاتية",
    ] if w in text_lower)
    jd_indicators = sum(1 for w in [
        "we are looking", "we are seeking", "job description",
        "responsibilities include", "requirements:", "about the role",
        "what you'll do", "what you will do", "we offer", "salary range",
        "benefits package", "apply now", "apply by", "working hours",
        "contract type", "you will be responsible", "you will have",
        "ideal candidate", "minimum qualifications", "preferred qualifications",
        "equal opportunity employer",
    ] if w in text_lower)

    if jd_indicators >= 3 and cv_indicators <= 1:
        return "OTHER", 0, 0
    if cv_indicators >= 3:
        return "CV", 0, 0
    if not api_key:
        return "CV", 0, 0

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=5,
            messages=[{
                "role": "user",
                "content": (
                    "Is this document a CV/resume, or is it something else such as a "
                    "job offer, job description, contract, or other document? "
                    "Reply with only one word: CV or OTHER\n\n"
                    + text[:3000]
                ),
            }],
        )
        in_tok = response.usage.input_tokens if response.usage else 0
        out_tok = response.usage.output_tokens if response.usage else 0
        answer = response.content[0].text.strip().upper()
        return ("OTHER" if "OTHER" in answer else "CV"), in_tok, out_tok
    except Exception:
        return "CV", 0, 0  # fail safe — never block a valid CV


# ── Training parser ───────────────────────────────────────────────────────────

def _parse_training(text: str) -> list[dict]:
    """Parse professional training / courses section into structured entries."""
    if not text:
        return []

    _YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
    _SKIP_HEADINGS = {"COMPUTER SKILLS", "REFERENCES", "HOBBIES", "LANGUAGE", "LANGUAGES"}

    raw_lines = [
        l.strip(" \u2022\uf0b7\u2022-\u2013\u2014*\u00b7").strip()
        for l in text.splitlines()
        if l.strip(" \u2022\uf0b7\u2022-\u2013\u2014*\u00b7").strip()
    ]
    lines = [l for l in raw_lines if len(l) > 3]

    buckets: list[list[str]] = []
    for line in lines:
        if _YEAR_RE.search(line):
            buckets.append([line])
        elif buckets:
            buckets[-1].append(line)

    entries = []
    for bucket in buckets:
        if not bucket:
            continue
        primary = bucket[0]
        if any(skip in primary.upper() for skip in _SKIP_HEADINGS):
            continue
        # Split on " - " or " | " with surrounding spaces (not bare hyphens,
        # so names like SHRM-SCP are preserved)
        parts = re.split(r"\s+[-|]\s+", primary)
        name = parts[0].strip() if parts else primary
        org = parts[1].strip() if len(parts) > 1 else ""
        desc_parts = parts[3:] if len(parts) > 3 else []
        years = _YEAR_RE.findall(primary)
        date = years[0] if years else ""
        name_clean = _YEAR_RE.sub("", name).strip(" -|")
        org_clean = _YEAR_RE.sub("", org).strip(" -|")
        desc_frags = [_YEAR_RE.sub("", p).strip(" -|") for p in desc_parts]
        desc_frags += bucket[1:]
        description = " ".join(d for d in desc_frags if d)
        if name_clean and len(name_clean) > 3:
            entries.append({
                "name": name_clean,
                "organisation": org_clean,
                "date": date,
                "description": description,
            })
    return entries


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


def _extract_fallback_summary(raw_text: str) -> str:
    """Extract first substantial paragraph as summary when no summary heading found."""
    paragraphs = re.split(r"\n{2,}", raw_text.strip())
    for para in paragraphs:
        lines = [l.strip() for l in para.splitlines() if l.strip()]
        text = " ".join(lines)
        if len(text.split()) < 15:
            continue
        if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
            continue
        # Skip all-caps headings
        if re.match(r"^[A-Z\s]{3,30}$", text.strip()):
            continue
        if any(text.lower().startswith(p) for p in (
            "address", "tel", "mobile", "phone", "email", "date of birth",
            "nationality", "place of birth",
        )):
            continue
        return text
    return ""


def _parse_experience_blocks(text: str) -> list[dict]:
    """Simple block-based fallback when date-anchored parser finds nothing."""
    if not text:
        return []
    entries = []
    blocks = re.split(r"\n{2,}", text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines or len(lines) < 2:
            continue
        bullets = []
        title_line = ""
        for line in lines:
            if line[:1] in ("•", "-", "–", "*", "\u2022", "\uf0b7"):
                bullet = re.sub(r"^[•\-–*\u2022\uf0b7]\s*", "", line).strip()
                if bullet:
                    bullets.append(bullet)
            elif not title_line:
                title_line = line
        if title_line or bullets:
            entries.append({
                "title": title_line,
                "company": "",
                "location": "",
                "start_date": "",
                "end_date": "",
                "bullets": bullets,
            })
    return entries

def _extract_arabic_cv_via_claude(
    pdf_bytes: bytes,
    arabic_raw_text: str,
    api_key: str,
) -> tuple[dict, int, int]:
    """Call Claude to extract and translate an Arabic PDF CV into structured English CVData.

    Returns (cv_data dict, input_tokens, output_tokens).
    Uses the same key structure as the English parse path — no separate keys.
    """
    import json

    try:
        import streamlit as _st
        _st.toast("🌐 Arabic CV detected — using Claude to extract and translate…", icon="🔤")
    except Exception:
        pass

    b64 = base64.standard_b64encode(pdf_bytes).decode()
    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        "This CV/resume is written in Arabic. "
        "Extract all information and return it translated into English as a valid JSON object. "
        "Use EXACTLY these keys (omit keys that have no data — do not set empty strings or empty lists "
        "unless genuinely empty):\n\n"
        "{\n"
        '  "name": "Full name in English (transliterate if needed)",\n'
        '  "title": "Professional title in English",\n'
        '  "email": "email address",\n'
        '  "phones": ["phone number 1", "phone number 2"],\n'
        '  "location": "City, Country in English",\n'
        '  "linkedin": "linkedin URL or username",\n'
        '  "website": "website URL",\n'
        '  "dob": "date of birth",\n'
        '  "neighbourhood": "district or neighbourhood name in English if present",\n'
        '  "military_status": "military service status in English if present (e.g. Exempted, Completed)",\n'
        '  "nationality": "nationality in English",\n'
        '  "summary": "Professional summary translated into fluent English",\n'
        '  "experience": [\n'
        '    {\n'
        '      "title": "Job title in English",\n'
        '      "company": "Company name",\n'
        '      "location": "City",\n'
        '      "start_date": "Month Year",\n'
        '      "end_date": "Month Year or Present",\n'
        '      "bullets": ["Key achievement or responsibility in English"]\n'
        '    }\n'
        '  ],\n'
        '  "education": [\n'
        '    {\n'
        '      "degree": "Degree name in English",\n'
        '      "institution": "Institution name",\n'
        '      "location": "City",\n'
        '      "year": "Graduation year",\n'
        '      "gpa": "",\n'
        '      "honors": ""\n'
        '    }\n'
        '  ],\n'
        '  "skills_core": ["Core competency 1", "Core competency 2"],\n'
        '  "skills_technical": ["Tool or technology 1", "Tool or technology 2"],\n'
        '  "training": [\n'
        '    {"name": "Course name in English", "organisation": "Provider", "date": "Year", "description": ""}\n'
        '  ],\n'
        '  "languages": ["Arabic (Native)", "English (Fluent)"],\n'
        '  "certifications": [\n'
        '    {"name": "Certificate name in English", "issuer": "Issuing body", "date": "Year"}\n'
        '  ]\n'
        "}\n\n"
        "Return ONLY the JSON object — no markdown fences, no explanation, no surrounding text."
    )

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
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except Exception as exc:
        try:
            import streamlit as _st
            _st.warning(f"Arabic CV extraction failed: {exc} — falling back to raw text parse.")
        except Exception:
            pass
        raise

    in_tok  = response.usage.input_tokens  if response.usage else 0
    out_tok = response.usage.output_tokens if response.usage else 0
    raw_json = response.content[0].text.strip()

    # Strip markdown code fences if model added them anyway
    raw_json = re.sub(r"^```(?:json)?\s*", "", raw_json)
    raw_json = re.sub(r"\s*```$", "", raw_json)

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        # Best-effort: find first {...} block
        m = re.search(r"\{.*\}", raw_json, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}

    # Normalise phones
    phones = data.get("phones") or []
    if isinstance(phones, str):
        phones = [p.strip() for p in phones.split("|") if p.strip()]
    phone = " | ".join(phones)

    # Build skills dict from skills_core / skills_technical (same structure as English path)
    skills_core = data.get("skills_core") or []
    skills_tech  = data.get("skills_technical") or []
    categories = []
    if skills_tech:
        categories.append({"name": "Technical Competencies", "items": skills_tech})
    if skills_core:
        categories.append({"name": "Core Competencies", "items": skills_core})
    if not categories:
        categories = [{"name": "Skills", "items": []}]
    skills = {"categories": categories}

    cv_data: dict = {
        "name":           data.get("name", ""),
        "title":          data.get("title", ""),
        "email":          data.get("email", ""),
        "phones":         phones,
        "phone":          phone,
        "location":       data.get("location", ""),
        "linkedin":       data.get("linkedin", ""),
        "website":        data.get("website", ""),
        "dob":            data.get("dob", ""),
        "neighbourhood":  data.get("neighbourhood", ""),
        "military_status": data.get("military_status", ""),
        "nationality":    data.get("nationality", ""),
        "summary":        data.get("summary", ""),
        "experience":     data.get("experience") or [],
        "education":      data.get("education") or [],
        "skills":         skills,
        "certifications": data.get("certifications") or [],
        "training":       data.get("training") or [],
        "languages":      data.get("languages") or [],
        "projects":       data.get("projects") or [],
        "raw_text":       arabic_raw_text,  # preserve original Arabic text
    }
    # Sensitive fields detection
    _SENSITIVE_RE_AR = re.compile(
        r"\b\d{8,}\b"
        r"|\b(national\s+id|passport\s*(no|number|#)?|id\s*:|رقم\s*الهوية|رقم\s*جواز)",
        re.I,
    )
    _scan_ar = " ".join(filter(None, [cv_data.get("summary", ""), arabic_raw_text or ""]))
    if _SENSITIVE_RE_AR.search(_scan_ar):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "sensitive_fields_detected: possible ID/passport number found in CV"
        )
        cv_data["sensitive_fields_detected"] = True
    return cv_data, in_tok, out_tok


def parse_cv(
    file: BinaryIO,
    filename: str,
    api_key: str = "",
    check_doc_type: bool = True,
) -> tuple[dict, int, int]:
    """Parse an uploaded CV file. Returns (CVData dict, input_tokens, output_tokens).

    input_tokens / output_tokens accumulate all Claude API usage (vision extraction
    + optional document-type classification call).

    Raises NonCVDocumentError if the document appears to be a job offer / JD.
    """
    _ext = Path(filename).suffix.lower()
    if _ext not in {".pdf", ".docx", ".doc", ".txt"}:
        raise ValueError(
            "[RVZ-P004] Unsupported file format. Please upload a PDF, DOCX, or TXT file."
        )
    try:
        return _parse_cv_inner(file, filename, api_key=api_key, check_doc_type=check_doc_type)
    except NonCVDocumentError:
        raise
    except Exception as _e:
        err = raise_rvz("RVZ-U001", detail=f"parse_cv failed for {filename}: {_e}", exc=_e)
        raise ValueError(
            f"[{err.code}] Could not parse the uploaded file — {err.message}. Detail: {_e}"
        ) from _e


def _parse_cv_inner(
    file: BinaryIO,
    filename: str,
    api_key: str = "",
    check_doc_type: bool = True,
) -> tuple[dict, int, int]:
    """Internal implementation of parse_cv — see parse_cv for full docstring."""
    # Buffer file bytes so we can pass PDF data to Claude if Arabic is detected.
    # This must happen before extract_text() consumes the file pointer.
    _file_bytes = file.read()
    file = io.BytesIO(_file_bytes)

    raw_text, in_tok, out_tok = extract_text(file, filename, api_key=api_key)

    # ── Arabic CV detection ───────────────────────────────────────────────────
    # pdfminer and PyMuPDF can extract Arabic Unicode text successfully, but the
    # downstream section parsers (_parse_experience, _parse_education, etc.) are
    # Latin-only. When a PDF is predominantly Arabic, route to Claude for structured
    # English extraction using the same CVData key structure as the English path.
    _ext = Path(filename).suffix.lower()
    if _ext == ".pdf" and _is_arabic_dominant(raw_text) and api_key:
        try:
            arabic_cv, ar_in, ar_out = _extract_arabic_cv_via_claude(
                _file_bytes, raw_text, api_key
            )
            return arabic_cv, in_tok + ar_in, out_tok + ar_out
        except Exception:
            # Fall through to normal parse if Claude extraction fails
            pass

    # Classify document type (job offer detection) — only when API key available
    if check_doc_type and api_key and raw_text.strip():
        doc_type, cls_in, cls_out = _classify_document(raw_text, api_key)
        in_tok += cls_in
        out_tok += cls_out
        if doc_type == "OTHER":
            raise NonCVDocumentError(
                "The uploaded file does not appear to be a CV or resume. "
                "Please upload your CV file."
            )

    sections = _split_into_sections(raw_text)
    non_header = [k for k in sections if k != "header"]
    if not non_header:
        raise_rvz("RVZ-E003", detail=f"Sections found: {list(sections.keys())}")
    contact = _extract_contact(sections.get("header", ""))

    # DOB: prefer header extraction; fall back to scanning full raw_text
    # with multiple patterns to maximise coverage.
    dob = contact.pop("dob", "")
    if not dob:
        for _pat in _DOB_PATTERNS:
            _m = _pat.search(raw_text)
            if _m:
                dob = _m.group(1).strip()
                break

    # Military status: scan full raw text for service phrases
    military_status = ""
    try:
        _MIL_RE = re.compile(
            r"(?:military\s+(?:service|status)\s*[:\-]?\s*\S[^\n]*"
            r"|(?:exempted|completed|postponed|fulfilled)\s+(?:from\s+)?military[^\n]*"
            r"|خدمة\s*عسكرية[^\n]*"
            r"|معفي[^\n]*"
            r"|أدى\s+الخدمة[^\n]*)",
            re.I,
        )
        mil_m = _MIL_RE.search(raw_text)
    except re.error as _mil_err:
        raise_rvz("RVZ-P005", detail=f"Pattern: military_re — {_mil_err}", exc=_mil_err)
        mil_m = None
    if mil_m:
        military_status = mil_m.group(0).strip()

    cv_data: dict = {
        **contact,
        "dob":            dob,
        "military_status": military_status,
        "summary":        sections.get("summary", "").strip(),
        "experience":     _parse_experience(sections.get("experience", "")),
        "education":      _parse_education(sections.get("education", "")),
        "skills":         _parse_skills(sections.get("skills", "")),
        "certifications": _parse_certifications(sections.get("certifications", "")),
        "training":       _parse_training(sections.get("training", "")),
        "languages":      _parse_languages(sections.get("languages", "")),
        "projects":       _parse_projects(sections.get("projects", "")),
        "raw_text":       raw_text,
    }
    # Fallback summary: if section splitter found nothing, use first substantial paragraph
    if not cv_data["summary"]:
        cv_data["summary"] = _extract_fallback_summary(raw_text)
    # Fallback experience: if date-anchored parser found nothing, try block-based parse
    if not cv_data["experience"] and sections.get("experience", "").strip():
        cv_data["experience"] = _parse_experience_blocks(sections["experience"])
    # Fallback: if no language section was detected, scan raw text for language names
    if not cv_data["languages"] and raw_text:
        cv_data["languages"] = _fallback_language_scan(raw_text)
    # Sensitive fields detection: scan free-text fields for ID/passport numbers or labels
    _SENSITIVE_RE = re.compile(
        r"\b\d{8,}\b"                          # 8+ consecutive digits (ID/passport number)
        r"|\b(national\s+id|passport\s*(no|number|#)?|id\s*:|رقم\s*الهوية|رقم\s*جواز)",
        re.I,
    )
    _scan_targets = " ".join(filter(None, [
        cv_data.get("summary", ""),
        cv_data.get("raw_text", ""),
    ]))
    if _SENSITIVE_RE.search(_scan_targets):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "sensitive_fields_detected: possible ID/passport number found in CV"
        )
        cv_data["sensitive_fields_detected"] = True
    return cv_data, in_tok, out_tok
