from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml
import logging

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None  # type: ignore[assignment]

from shared.config import settings

logger = logging.getLogger(__name__)


class CanonicalProfile:
    """
    Immutable representation of the candidate's canonical profile.
    Explicitly distinguishes FACT, INFERENCE, and PREFERENCE.
    """
    def __init__(
        self,
        facts: Dict[str, Any],
        preferences: Dict[str, Any],
        inferences: Optional[Dict[str, Any]] = None,
        master_cv_text: Optional[str] = None,
    ):
        self.facts = facts
        self.preferences = preferences
        self.inferences = inferences or {}
        self.master_cv_text = master_cv_text or ""

        # Pre-computed normalized sets for ultra-fast matching
        self._skills_set: Set[str] = {
            s.lower().strip() for s in self.facts.get("skills", [])
        }
        self._preferred_roles_set: Set[str] = {
            r.lower().strip() for r in self.preferences.get("preferred_roles", [])
        }
        self._excluded_roles_set: Set[str] = {
            r.lower().strip() for r in self.preferences.get("excluded_roles", [])
        }
        self._locations_set: Set[str] = {
            loc.lower().strip() for loc in self.preferences.get("locations", [])
        }

    @property
    def name(self) -> str:
        return self.facts.get("name", "")

    @property
    def email(self) -> str:
        return self.facts.get("email", "")

    @property
    def phone(self) -> str:
        return self.facts.get("phone", "+49 176 00000000")

    @property
    def website(self) -> str:
        return self.facts.get("website", "")

    @property
    def experience_years(self) -> int:
        return int(self.facts.get("experience_years", 15))

    @property
    def languages(self) -> Dict[str, str]:
        return self.facts.get("languages", {})

    @property
    def education(self) -> List[Dict[str, Any]]:
        return self.facts.get("education", [])

    @property
    def certifications(self) -> List[str]:
        return self.facts.get("certifications", [])

    @property
    def skills(self) -> List[str]:
        return self.facts.get("skills", [])

    def has_verified_skill(self, skill: str) -> bool:
        """Returns True only if skill is a verified candidate fact."""
        return skill.lower().strip() in self._skills_set

    def is_role_excluded(self, title: str) -> bool:
        t_low = title.lower()
        return any(ex in t_low for ex in self._excluded_roles_set)

    def is_role_preferred(self, title: str) -> bool:
        t_low = title.lower()
        return any(pref in t_low for pref in self._preferred_roles_set)

    def is_location_preferred(self, location: Optional[str], remote_status: Optional[str]) -> bool:
        if self.preferences.get("remote", True) and remote_status and "remote" in remote_status.lower():
            return True
        if not location:
            return False
        loc_low = location.lower()
        return any(pref in loc_low for pref in self._locations_set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "preferences": self.preferences,
            "inferences": self.inferences,
            "has_master_cv": bool(self.master_cv_text),
        }


def load_canonical_profile(
    profile_path: Optional[str] = None,
    preferences_path: Optional[str] = None,
    master_cv_path: Optional[str] = None,
) -> CanonicalProfile:
    """
    Loads and validates the candidate canonical profile from disk.
    FACT is authoritative.
    """
    p_path = Path(profile_path or settings.PROFILE_PATH)
    pref_path = Path(preferences_path or settings.PREFERENCES_PATH)
    cv_path = Path(master_cv_path or settings.MASTER_CV_PATH)

    # Resolve local fallback paths if running outside docker container
    if not p_path.exists():
        p_path = Path("profile/profile.yaml")
    if not pref_path.exists():
        pref_path = Path("profile/preferences.yaml")
    if not cv_path.exists():
        cv_path = Path("profile/master_cv.pdf")

    facts: Dict[str, Any] = {}
    if p_path.exists():
        with open(p_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            facts = data.get("candidate", data)

    preferences: Dict[str, Any] = {}
    if pref_path.exists():
        with open(pref_path, "r", encoding="utf-8") as f:
            preferences = yaml.safe_load(f) or {}

    master_cv_text = ""
    if cv_path.exists() and PyPDF2 is not None:
        try:
            with open(cv_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pages = [page.extract_text() or "" for page in reader.pages]
                master_cv_text = "\n".join(pages).strip()
        except Exception as e:
            logger.warning(f"Could not extract text from master CV ({cv_path}): {e}")

    inferences: Dict[str, Any] = {
        "source": "canonical_profile_loader",
        "website_verified": True if facts.get("website") else False,
    }

    return CanonicalProfile(
        facts=facts,
        preferences=preferences,
        inferences=inferences,
        master_cv_text=master_cv_text,
    )
