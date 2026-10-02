"""Lever application-site adapter (T6).

Covers jobs.lever.co application forms: full-name field, e-mail, phone,
resume upload, LinkedIn URL, comments/cover-letter textarea, EEO work
authorization select, salary expectation. Shares the generic
accessible-locator-first behavior; kept separate so Lever-specific flows
can diverge without touching the generic fallback.

PREPARE-only: no submit() exists on adapters by design; submission stays
in BrowserAutomationEngine behind confirmed=True + FULL_AUTO.
"""
from browser.site_adapters.generic import GenericAdapter as _Generic


class LeverAdapter(_Generic):
    name = "lever"

    def matches(self, url: str) -> bool:
        lowered = url.lower()
        return "lever.co" in lowered or "lever" in lowered
