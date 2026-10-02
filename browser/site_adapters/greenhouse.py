"""Greenhouse application-site adapter (T6).

Covers boards.greenhouse.io / job-boards.greenhouse.io application forms:
separate first/last name, e-mail, phone, resume + cover-letter upload,
LinkedIn URL, plus screening questions (experience years, work
authorization). Shares the generic accessible-locator-first behavior;
kept separate so Greenhouse-specific flows can diverge without touching
the generic fallback.

PREPARE-only: no submit() exists on adapters by design; submission stays
in BrowserAutomationEngine behind confirmed=True + FULL_AUTO.
"""
from browser.site_adapters.generic import GenericAdapter as _Generic


class GreenhouseAdapter(_Generic):
    name = "greenhouse"

    def matches(self, url: str) -> bool:
        lowered = url.lower()
        return "greenhouse.io" in lowered or "greenhouse" in lowered or "gh_src" in lowered
