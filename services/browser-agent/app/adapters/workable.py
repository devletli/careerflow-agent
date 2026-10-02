"""Workable application-site adapter.

Currently shares the generic accessible-locator-first behavior; kept as a
separate adapter so Workable-specific flows can diverge without touching the
generic fallback.
"""
from .generic import GenericAdapter


class WorkableAdapter(GenericAdapter):
    name = "workable"

    @classmethod
    def matches(cls, url: str) -> bool:
        return "workable.com" in url.lower()
