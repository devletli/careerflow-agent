"""PII redaction for log records.

Masks e-mail addresses, phone-like numbers, and the candidate name/surname
from profile.yaml. Active only when settings.LOG_REDACT_PII is true.
Timestamps, IP addresses, ports, and short numbers are never masked.
"""
import logging
import re
from pathlib import Path
from typing import List, Optional

MASK = "***"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Digit runs with phone-like separators; the digit-count guard (9-15) plus
# the exclusions below keep timestamps, dates, IPs, ports, and versions untouched.
PHONE_RE = re.compile(r"\+?[\d][\d\s().-]*\d")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_TOKEN = "\ue000DATE\ue001"


def _digit_count(value: str) -> int:
    return sum(ch.isdigit() for ch in value)


def _mask_phone(match: "re.Match") -> str:
    text = match.group(0)
    if ":" in text:
        return text  # timestamps, IP:port, durations
    if not 9 <= _digit_count(text) <= 15:
        return text
    return MASK


_names_cache: Optional[List[str]] = None


def _candidate_names(profile_path: Optional[str] = None) -> List[str]:
    """Loads candidate name parts from profile.yaml (cached, best-effort)."""
    global _names_cache
    if _names_cache is not None:
        return _names_cache
    _names_cache = []
    try:
        from shared.config import settings as _settings

        path = Path(profile_path or _settings.PROFILE_PATH)
        if not path.exists():
            path = Path("profile/profile.yaml")
        if path.exists():
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            name = (data.get("candidate", data) or {}).get("name", "")
            if isinstance(name, str) and name.strip():
                _names_cache = [name.strip()]
                _names_cache.extend(part for part in name.split() if len(part) >= 3)
    except Exception:
        pass
    return _names_cache


def reset_names_cache() -> None:
    global _names_cache
    _names_cache = None


def redact(text: str, profile_path: Optional[str] = None) -> str:
    """Returns text with e-mail, phone, and candidate-name values masked."""
    redacted = EMAIL_RE.sub(MASK, text)
    dates: list = []
    redacted = _protect_dates(redacted, dates)
    redacted = PHONE_RE.sub(_mask_phone, redacted)
    for i, value in enumerate(dates):
        redacted = redacted.replace(f"{_DATE_TOKEN}{i}{_DATE_TOKEN}", value)
    for name in _candidate_names(profile_path):
        if name:
            redacted = redacted.replace(name, MASK)
    return redacted


def _protect_dates(text: str, dates: list) -> str:
    def _tokenize(match: "re.Match") -> str:
        dates.append(match.group(0))
        return f"{_DATE_TOKEN}{len(dates) - 1}{_DATE_TOKEN}"

    return DATE_RE.sub(_tokenize, text)


class PiiRedactingFilter(logging.Filter):
    """Logging filter applying redact() to the rendered record message."""

    def filter(self, record: logging.LogRecord) -> bool:
        from shared.config import settings

        if not settings.LOG_REDACT_PII:
            return True
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def install_pii_redaction() -> None:
    """Attaches the redacting filter to the root logger (idempotent)."""
    root = logging.getLogger()
    if not any(isinstance(f, PiiRedactingFilter) for f in root.filters):
        root.addFilter(PiiRedactingFilter())
