"""Claude API CV optimization engine.

Produces two outputs per session:
1. General ATS-optimized CV (always generated when online)
2. JD-tailored CV (generated when a job description is provided)

Both outputs follow the same CVData schema as the parser.
"""

from __future__ import annotations

import json
import re

import anthropic

from revizor_frank.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS

# ── CV schema reference sent to Claude ────────────────────────────────────────

_CV_SCHEMA = {
    "name": "string",
    "title": "string (professional title/designation, e.g. 'Senior Internal Auditor | Finance Professional')",
    "email": "string",
    "phone": "string (all phone numbers pipe-separated, e.g. +20123456789 | +447521002142)",
    "location": "string",
    "neighbourhood": "string (district/area within the city, if provided — preserve exactly)",
    "linkedin": "string",
    "github": "string (GitHub profile URL, if present)",
    "website": "string",
    "dob": "string — labelled 'Date of Birth' in output, preserve value exactly",
    "nationality": "string (e.g. 'Egyptian' — preserve exactly)",
    "marital_status": "string (e.g. 'Single', 'Married' — preserve exactly, leave empty if absent)",
    "military_status": "string (military service status if provided, e.g. 'Exempted', 'Completed' — preserve exactly, leave empty if absent)",
    "summary": "string (60-100 words, third-person implied, no first-person pronouns)",
    "experience": [
        {
            "title": "string",
            "company": "string",
            "location": "string",
            "start_date": "string (e.g. Jan 2020)",
            "end_date": "string (e.g. Dec 2023 or Present)",
            "bullets": ["string (strong action verb, quantified where possible)"],
        }
    ],
    "education": [
        {
            "degree": "string",
            "institution": "string",
            "location": "string",
            "year": "string",
            "gpa": "string",
            "honors": "string",
        }
    ],
    "skills": {
        "categories": [
            {"name": "Core Competencies", "items": ["skill1", "skill2"]},
            {"name": "Technical Competencies", "items": ["tool1", "tool2"]},
        ]
    },
    "certifications": [{"name": "string", "issuer": "string", "date": "string"}],
    "training": [{"name": "string", "organisation": "string", "date": "string", "description": "string"}],
    "languages": ["string"],
    "projects": [{"name": "string", "description": "string", "technologies": ["string"]}],
    "flags": [{"section": "string", "issue": "string — description of what was detected but not changed"}],
    "skill_validation_questions": [
        "string — a specific question to ask the candidate to validate or expand on a listed skill"
    ],
}

_LINKEDIN_SCHEMA = {
    "headline": "string (max 220 chars — title | skill | value prop | industry)",
    "about": "string (max 2600 chars — compelling narrative, first-person OK on LinkedIn)",
    "experience": [
        {
            "title": "string",
            "company": "string",
            "dates": "string (e.g. Jan 2020 – Present)",
            "description": "string (LinkedIn-optimized, story-driven, max 2000 chars)",
        }
    ],
    "skills": ["string (max 50 skills, ranked by relevance)"],
    "education": [{"degree": "string", "school": "string", "dates": "string"}],
    "certifications": [{"name": "string", "issuer": "string", "date": "string"}],
    "summary_tagline": "string (one punchy sentence for connection requests / InMail)",
}


# ── Prompt builders ───────────────────────────────────────────────────────────

_PROMPT_STRIP_KEYS = frozenset(["phones", "session_id", "_filename"])
_PROMPT_STRIP_KEYS_NO_RAW = frozenset(["raw_text", "phones", "session_id", "_filename"])


def _clean_for_prompt(cv: dict, keep_raw_text: bool = False) -> dict:
    """Return a copy of cv with internal/noise fields removed before sending to Claude.

    By default strips raw_text too (safe for JD/LinkedIn prompts where it adds
    noise). Pass keep_raw_text=True for the general prompt which cross-references
    raw_text against parsed fields.
    """
    strip = _PROMPT_STRIP_KEYS if keep_raw_text else _PROMPT_STRIP_KEYS_NO_RAW
    return {k: v for k, v in cv.items() if k not in strip}


def _build_general_prompt(cv_data: dict) -> str:
    return f"""You are a world-class HR consultant, executive CV writer, and ATS optimization expert.

Your task: Transform the provided CV data into the best possible version for ATS systems and human readers.

RULES:
1. Fix ALL grammar, spelling, and punctuation errors.
2. Replace weak/passive verbs with strong action verbs (Led, Built, Drove, Delivered, etc.).
3. Quantify achievements wherever plausible — add realistic estimates flagged with ≈ prefix. NEVER invent specifics.
4. Write summary as: professional journey + key competencies + top achievements. Third-person implied (no "I", "my", "me"). 60–100 words.
5. Use consistent date format: "Mon YYYY" (e.g. Jan 2020). Use "Present" for current roles.
6. NEVER invent experience, companies, degrees, or certifications — only improve what exists.
7. Preserve ALL training, certification, and project entries exactly — do not drop any.
8. Skills MUST be split into exactly two categories: "Core Competencies" (leadership, management, communication, strategy, interpersonal) and "Technical Competencies" (software, tools, platforms, systems, technical methods). No other category names permitted.
9. Core Competencies must always appear BEFORE Technical Competencies in the output.
10. Experience entries must be ordered most recent first.
11. Education entries must be ordered most recent first.
12. Preserve the candidate's professional title exactly. If absent, infer from most recent role.
13. Phone: preserve all mobile numbers with country code. If a number has no country code, do not add one — flag it with a ≈ prefix in the phone field.
14. LinkedIn: store the profile URL or username exactly as provided. Do not reformat.
15. NEVER include national ID numbers, passport numbers, age, or gender in the output unless the job posting explicitly requires it.
16. Preserve neighbourhood, military_status, dob, and nationality fields exactly as provided — do not infer, modify, or remove them.
17. Always write all output in English. The input has already been translated if needed.
18. HIGHLIGHT — do not fix — any section where content appears incomplete, inconsistent, or where information seems missing. Flag these sections in the "flags" array: [{{"section": "experience", "issue": "description of what was detected but not changed"}}]. The co-worker reviews flags before finalising.

INPUT CV DATA:
{json.dumps(_clean_for_prompt(cv_data), indent=2)}

OUTPUT: Return ONLY a valid JSON object matching this schema exactly — no markdown, no commentary:
{json.dumps(_CV_SCHEMA, indent=2)}
"""


def _build_jd_prompt(cv_data: dict, job_description: str, general_cv: dict) -> str:
    return f"""You are a world-class HR consultant and ATS optimization expert specializing in CV-to-job-description matching.

Your task: Adapt the already-optimized CV to maximize keyword and skill alignment with the provided job description.

CRITICAL RULES:
1. Mirror the JD's exact language for skills, tools, and responsibilities where you can honestly match them to the candidate's background
2. Reorder and rewrite bullets to lead with the JD's most important requirements
3. Update the summary to speak directly to this specific role
4. Add JD keywords naturally — NEVER keyword-stuff or repeat keywords unnaturally
5. NEVER invent experience or qualifications the candidate does not have
6. Reorder skills to put JD-matching skills first
7. Identify and include every relevant keyword from the JD that the candidate can legitimately claim
8. Keep all dates, companies, and factual details from the original — only language changes
9. Always write all output in English regardless of the original CV language.

JOB DESCRIPTION:
{job_description}

OPTIMIZED CV (base for tailoring):
{json.dumps(_clean_for_prompt(general_cv), indent=2)}

ORIGINAL PARSED CV (for reference):
{json.dumps(_clean_for_prompt(cv_data), indent=2)}

OUTPUT: Return ONLY a valid JSON object matching this schema exactly — no markdown, no commentary:
{json.dumps(_CV_SCHEMA, indent=2)}
"""


def _build_linkedin_prompt(cv_data: dict, general_cv: dict, job_description: str = "") -> str:
    jd_section = f"\nJOB DESCRIPTION (target role for optimization):\n{job_description}" if job_description else ""
    return f"""You are a LinkedIn profile optimization expert and personal branding specialist.

Your task: Create a complete, compelling LinkedIn profile from the provided CV data.

LinkedIn-specific RULES:
1. Headline: Max 220 chars. Formula: [Title] | [Key Skill] | [Value Prop] | [Industry/Niche]
2. About: Max 2600 chars. First-person IS appropriate on LinkedIn. Open with a hook, tell a story, end with CTA.
3. Experience descriptions: More narrative than CV bullets — tell the story behind the achievement
4. Skills: List up to 50 skills ordered by relevance; include both hard and soft skills
5. Make every word earn its place — LinkedIn has billions of profiles; stand out
6. Include relevant keywords naturally for LinkedIn Search Algorithm (LSA)
7. Avoid resume-speak in the About section — LinkedIn is a networking tool, not an ATS
8. Summary tagline: One memorable sentence that captures the candidate's unique value{jd_section}

OPTIMIZED CV DATA:
{json.dumps(_clean_for_prompt(general_cv), indent=2)}

OUTPUT: Return ONLY a valid JSON object matching this schema exactly — no markdown, no commentary:
{json.dumps(_LINKEDIN_SCHEMA, indent=2)}
"""


# ── JSON extractor ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract JSON from Claude's response, handling markdown code blocks."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    return json.loads(text)


# ── API client ────────────────────────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _call_claude(prompt: str) -> tuple[str, int, int]:
    """Call Claude and return (text, input_tokens, output_tokens)."""
    client = _get_client()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0
    return response.content[0].text, input_tokens, output_tokens


# ── Public API ────────────────────────────────────────────────────────────────

def _preserve_passthrough_fields(result: dict, cv_data: dict) -> None:
    """Copy fields that Claude may omit back into the result dict (in-place).

    raw_text is intentionally excluded — it belongs only on parsed_cv and must
    never be written onto an AI-generated output dict.
    """
    for field in ("dob", "linkedin", "website", "neighbourhood", "military_status"):
        if not result.get(field) and cv_data.get(field):
            result[field] = cv_data[field]
    # Training entries — preserve if Claude omits them
    if not result.get("training") and cv_data.get("training"):
        result["training"] = cv_data["training"]
    result.setdefault("training", [])


def optimize_general(cv_data: dict) -> tuple[dict, int, int]:
    """Return (claude-optimized general ATS CV, input_tokens, output_tokens)."""
    prompt = _build_general_prompt(cv_data)
    raw, input_tokens, output_tokens = _call_claude(prompt)
    result = _extract_json(raw)
    result.setdefault("flags", [])
    _preserve_passthrough_fields(result, cv_data)
    return result, input_tokens, output_tokens


def optimize_jd_tailored(cv_data: dict, job_description: str, general_cv: dict) -> tuple[dict, int, int]:
    """Return (claude-optimized JD-tailored CV, input_tokens, output_tokens)."""
    prompt = _build_jd_prompt(cv_data, job_description, general_cv)
    raw, input_tokens, output_tokens = _call_claude(prompt)
    result = _extract_json(raw)
    result.setdefault("flags", [])
    _preserve_passthrough_fields(result, cv_data)
    return result, input_tokens, output_tokens


def generate_linkedin(cv_data: dict, general_cv: dict, job_description: str = "") -> tuple[dict, int, int]:
    """Return (claude-generated LinkedIn profile dict, input_tokens, output_tokens)."""
    prompt = _build_linkedin_prompt(cv_data, general_cv, job_description)
    raw, input_tokens, output_tokens = _call_claude(prompt)
    return _extract_json(raw), input_tokens, output_tokens
