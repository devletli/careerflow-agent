"""Deterministic grounding validation for generated documents.

Checks that CV/cover-letter output contains only claims grounded in the
candidate profile. Job-advert keywords that are NOT in the profile must never
appear in generated artifacts (ATS tailoring selects from verified skills).

The optional `allow` parameter carries caller-known legitimate strings
(target company/title, letterhead date) so the template's own application
header is not flagged.
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from shared.profile.tech_vocab import KNOWN_TECH_VOCAB


@dataclass
class Violation:
    kind: str  # "employer" | "skill" | "metric" | "date" | "degree" | "authorship"
    claim: str


def extract_numbers(text: str) -> set[str]:
    return {match.strip() for match in re.findall(r"\d+(?:[.,]\d+)?\s?%?", text)}


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DATE_RANGE_RE = re.compile(
    r"\b(?:19|20)\d{2}\s*[-–/]\s*(?:19|20)?\d{2,4}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}"
    r"\s*[-–]\s*(?:[a-z]+\s+)?\d{4}\b",
    re.IGNORECASE,
)
_DEGREE_HINTS = [
    "bachelor",
    "master",
    "phd",
    "ph.d",
    "b.sc",
    "m.sc",
    "bachelor's",
    "master's",
    "diplom",
    "doctorate",
]
_ORG_RE = re.compile(
    r"\b([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*)\s+"
    r"(GmbH|AG|Inc|Ltd|LLC|Corp|UG|SE|SA|BV)\b"
)
# ai_assisted projesi varken "tek basima/elle yazdim" iddiasi durust degildir.
_SOLE_AUTHORSHIP_PATTERNS = [
    r"tamamen\s+elle",
    r"tamamını\s+kendim",
    r"tamamen\s+manuel",
    r"tek\s+baş(ı|i)ma\s+(yazdım|geliştirdim|yaptım)",
    r"fully\s+hand-?written",
    r"entirely\s+(hand-?written|by\s+hand|manually)",
    r"written\s+entirely\s+by\s+hand",
    r"without\s+any\s+ai\b",
    r"no\s+ai\s+assistance",
    r"100%\s+manual",
]
_WORKED_AT_RE = re.compile(
    r"(?:worked at|employed by|joined)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*)",
)


def _allowed(claim: str, allow: Sequence[str]) -> bool:
    claim_low = claim.lower()
    return any(claim_low in item.lower() for item in allow if item)


def _profile_numbers(profile: Dict[str, Any]) -> set[str]:
    return extract_numbers(str(profile))


def _profile_skills(profile: Dict[str, Any]) -> set[str]:
    return {s.lower() for s in profile.get("skills", []) if isinstance(s, str)}


def _skill_covered(tech: str, allowed_skills: set[str], extra_terms: set[str]) -> bool:
    tech_low = tech.lower()
    if any(tech_low == skill or tech_low in skill.split() for skill in allowed_skills):
        return True
    # Certifications/education mention the technology (e.g. "ISTQB Certified Tester").
    return tech_low in extra_terms


def _profile_edu_text(profile: Dict[str, Any]) -> str:
    parts = []
    for item in profile.get("education", []) or []:
        if isinstance(item, dict):
            parts.append(str(item.get("degree", "")))
            parts.append(str(item.get("institution", "")))
        else:
            parts.append(str(item))
    parts.extend(str(c) for c in profile.get("certifications", []) or [])
    return " ".join(parts).lower()


def validate_grounding(
    generated: str,
    profile: Dict[str, Any],
    allow: Sequence[str] = (),
    ai_assisted: bool = False,
) -> List[Violation]:
    """Returns grounding violations of generated text against the profile.

    ai_assisted=True iken "tamamen elle yazdim" turu tek-yazarlik
    iddialari da ihlal sayilir (durust ifade zorunlulugu).
    """
    violations: List[Violation] = []
    # Normalize extraction artifacts (PDF line breaks) before matching.
    text = re.sub(r"\s+", " ", generated)
    allow = [re.sub(r"\s+", " ", item) for item in allow]
    text_low = text.lower()

    # --- metrics: numbers must come from the profile (years not letterhead) ---
    for number in extract_numbers(text) - _profile_numbers(profile):
        if _YEAR_RE.fullmatch(number.strip()):
            continue  # years are handled by the date check below
        if _allowed(number.strip(), allow):
            continue
        violations.append(Violation("metric", number.strip()))

    # --- skills: known tech must be a verified profile skill ---
    allowed_skills = _profile_skills(profile)
    edu_terms = set(re.findall(r"[a-z0-9]+", _profile_edu_text(profile)))
    for tech in KNOWN_TECH_VOCAB:
        if re.search(rf"\b{re.escape(tech)}\b", text, re.IGNORECASE):
            if not _skill_covered(tech, allowed_skills, edu_terms) and not _allowed(tech, allow):
                violations.append(Violation("skill", tech))

    # --- degrees: degree wording must occur verbatim in profile education ---
    edu_text = _profile_edu_text(profile)
    for hint in _DEGREE_HINTS:
        if re.search(rf"\b{re.escape(hint)}\b", text_low) and hint not in edu_text:
            violations.append(Violation("degree", hint))

    # --- employers: organisation claims must be known ---
    known_orgs = {str(profile.get("name", "")).lower()}
    known_orgs.update(allowed_skills)
    for item in profile.get("education", []) or []:
        if isinstance(item, dict) and item.get("institution"):
            known_orgs.add(str(item["institution"]).lower())
    for match in list(_ORG_RE.finditer(text)) + list(_WORKED_AT_RE.finditer(text)):
        org = match.group(1)
        if org.lower() not in known_orgs and not _allowed(org, allow):
            violations.append(Violation("employer", org))

    # --- authorship: ai_assisted projede tek-yazarlik iddiasi yasak ---
    if ai_assisted:
        for pattern in _SOLE_AUTHORSHIP_PATTERNS:
            hit = re.search(pattern, text, re.IGNORECASE)
            if hit and not _allowed(hit.group(0), allow):
                violations.append(Violation("authorship", hit.group(0).strip()))

    # --- dates: employment date ranges must be allowlisted (e.g. letterhead) ---
    for match in _DATE_RANGE_RE.finditer(text):
        claim = match.group(0)
        if not _allowed(claim, allow):
            violations.append(Violation("date", claim))

    return violations
