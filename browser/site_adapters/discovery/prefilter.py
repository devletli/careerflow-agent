"""Cheap two-stage prefilter for discovery (Faz 2).

Uses only title/location/remote + preferences.yaml — never a score, never a
hard reject of the matching pipeline. Rejected items skip the expensive detail
fetch and the DB write; the decision is counted and reported in the
discovery-summary event so it stays visible.
"""

from typing import Any, Optional


def _contains(haystack: str, needle: str) -> bool:
    return needle.lower() in (haystack or "").lower()


def passes_prefilter(
    *,
    title: str,
    location: Optional[str],
    remote_status: Optional[str],
    text: Optional[str] = None,
    preferences: Optional[dict[str, Any]] = None,
) -> tuple[bool, Optional[str]]:
    """Returns (passed, reason). reason is None when passed."""
    prefs = preferences or {}
    title_l = (title or "").lower()

    for excluded in prefs.get("excluded_roles") or []:
        phrase = str(excluded or "").strip()
        if phrase and phrase.lower() in title_l:
            return False, f"excluded_role:{phrase}"

    preferred = [str(r or "").strip() for r in (prefs.get("preferred_roles") or []) if str(r or "").strip()]
    if preferred:
        haystack = f"{title} {text or ''}".lower()
        matched = False
        for role in preferred:
            words = [w for w in role.lower().split() if len(w) >= 3]
            if role.lower() in haystack or (words and all(w in haystack for w in words)):
                matched = True
                break
        if not matched:
            return False, "no_preferred_role_match"

    locations = [str(ll or "").strip().lower() for ll in (prefs.get("locations") or []) if str(ll or "").strip()]
    if locations:
        loc_l = (location or "").lower()
        is_remote = (remote_status or "").lower() == "remote"
        remote_ok = bool(prefs.get("remote", True)) and is_remote
        if loc_l or not remote_ok:
            if not any(_contains(loc_l, want) for want in locations) and not remote_ok:
                return False, "location_mismatch"

    return True, None
