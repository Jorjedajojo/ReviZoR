"""Centralised error registry for ReviZoR FranK."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import traceback
import logging

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    PARSE       = "PARSE"       # CV file reading / extraction
    EXTRACT     = "EXTRACT"     # Field extraction (name, email, etc.)
    AI          = "AI"          # Claude API calls
    EXPORT      = "EXPORT"      # PDF/DOCX/TXT generation
    SESSION     = "SESSION"     # Session save/restore
    NAV         = "NAV"         # Navigation / stage routing
    VALIDATION  = "VALIDATION"  # Missing fields, ATS checks
    REGEX       = "REGEX"       # Regex compilation or matching
    UNKNOWN     = "UNKNOWN"     # Uncategorised


# Error code registry — add new codes here
ERROR_CODES: dict[str, dict] = {
    "RVZ-P001": {"category": ErrorCategory.PARSE,      "message": "DOCX extraction returned empty text"},
    "RVZ-P002": {"category": ErrorCategory.PARSE,      "message": "PDF text extraction failed — no text layer found"},
    "RVZ-P003": {"category": ErrorCategory.PARSE,      "message": "Arabic PDF routing failed"},
    "RVZ-P004": {"category": ErrorCategory.PARSE,      "message": "File format not supported"},
    "RVZ-P005": {"category": ErrorCategory.REGEX,      "message": "Regex compilation error in parser"},
    "RVZ-E001": {"category": ErrorCategory.EXTRACT,    "message": "Name not detected in CV"},
    "RVZ-E002": {"category": ErrorCategory.EXTRACT,    "message": "Contact block extraction failed"},
    "RVZ-E003": {"category": ErrorCategory.EXTRACT,    "message": "Section splitter returned no sections"},
    "RVZ-A001": {"category": ErrorCategory.AI,         "message": "Claude API call failed — general optimisation"},
    "RVZ-A002": {"category": ErrorCategory.AI,         "message": "Claude API call failed — JD tailoring"},
    "RVZ-A003": {"category": ErrorCategory.AI,         "message": "Claude API call failed — Arabic extraction"},
    "RVZ-A004": {"category": ErrorCategory.AI,         "message": "Claude response was not valid JSON"},
    "RVZ-X001": {"category": ErrorCategory.EXPORT,     "message": "PDF export failed"},
    "RVZ-X002": {"category": ErrorCategory.EXPORT,     "message": "DOCX export failed"},
    "RVZ-X003": {"category": ErrorCategory.EXPORT,     "message": "LinkedIn export failed"},
    "RVZ-S001": {"category": ErrorCategory.SESSION,    "message": "Supabase save_session failed"},
    "RVZ-S002": {"category": ErrorCategory.SESSION,    "message": "Supabase load_session failed"},
    "RVZ-N001": {"category": ErrorCategory.NAV,        "message": "Stage transition blocked — missing prerequisite"},
    "RVZ-N002": {"category": ErrorCategory.NAV,        "message": "Finalise button reached with 0 sections"},
    "RVZ-V001": {"category": ErrorCategory.VALIDATION, "message": "Required fields missing after parse"},
    "RVZ-V002": {"category": ErrorCategory.VALIDATION, "message": "ATS check produced false positive on LinkedIn"},
    "RVZ-U001": {"category": ErrorCategory.UNKNOWN,    "message": "Unhandled exception"},
}


@dataclass
class ReviZoRError:
    code: str
    detail: str = ""
    exc: BaseException | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def category(self) -> ErrorCategory:
        return ERROR_CODES.get(self.code, {}).get("category", ErrorCategory.UNKNOWN)

    @property
    def message(self) -> str:
        return ERROR_CODES.get(self.code, {}).get("message", "Unknown error")

    def log(self):
        """Write to Streamlit Cloud logs with full traceback if available."""
        tb = ""
        if self.exc:
            tb = "".join(traceback.format_exception(type(self.exc), self.exc, self.exc.__traceback__))
        logger.error(
            "[%s] %s | %s | %s\n%s",
            self.code, self.category.value, self.message, self.detail, tb
        )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "category": self.category.value,
            "message": self.message,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


def raise_rvz(code: str, detail: str = "", exc: BaseException | None = None) -> ReviZoRError:
    """Create, log, and return a ReviZoRError. Does NOT raise — caller decides."""
    err = ReviZoRError(code=code, detail=detail, exc=exc)
    err.log()
    return err
