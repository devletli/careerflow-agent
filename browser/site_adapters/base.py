"""SiteAdapter interface for application-site form automation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from playwright.async_api import Page


@dataclass(frozen=True)
class FieldPlan:
    key: str  # e.g. "email", "resume"
    label_hint: str
    value: str | None  # None => no verified answer, leave to a human
    kind: str  # "text" | "select" | "file" | "checkbox"


@dataclass
class FillResult:
    filled: list[str] = field(default_factory=list)
    skipped_unverified: list[str] = field(default_factory=list)
    blocked_reason: str | None = None  # "CAPTCHA" | "LOGIN" | "MFA" | None
    submitted: bool = False


@runtime_checkable
class SiteAdapter(Protocol):
    name: str

    def matches(self, url: str) -> bool: ...
    async def detect_blockers(self, page: Page) -> str | None: ...
    async def fill(self, page: Page, plan: list[FieldPlan]) -> FillResult: ...
    # submit() is intentionally ABSENT: submit lives only in the Engine,
    # behind an explicit confirmation flag.
