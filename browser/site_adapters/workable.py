"""Workable application-site adapter.

Shares the generic accessible-locator-first behavior; kept separate so
Workable-specific flows can diverge without touching the generic fallback.
"""
from browser.site_adapters.generic import GenericAdapter as _Generic


class WorkableAdapter(_Generic):
    name = "workable"

    def matches(self, url: str) -> bool:
        return "workable.com" in url.lower()
