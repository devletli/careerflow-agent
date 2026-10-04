"""SiteAdapter interface for application-site form automation.

yama.md Faz 5A / architecture.md eslemesi (spec adi -> bu repodaki ad):
- detect(url) -> matches(url)
- discover_application(page) -> discover_application(page) (simdilik None)
- inspect_form(page) + map_fields(questions, profile) -> engine.build_plan
  (dogrulanmis cevaplardan; adapter'in isi degil)
- fill(page, plan) -> fill(page, plan)
- verify(page) -> verify_submission(page)
- submit_locator(page) -> submit_locator(page); TIKLAMAYI her zaman Engine
  yapar (BrowserAutomationEngine._click_submit). Adapter'da submit
  tiklamasi yoktur; PREPARE-only kural bununla kilitlenir.
"""
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
    confirmation_detected: bool = False


@runtime_checkable
class SiteAdapter(Protocol):
    name: str

    def matches(self, url: str) -> bool: ...
    async def detect_blockers(self, page: Page) -> str | None: ...
    async def fill(self, page: Page, plan: list[FieldPlan]) -> FillResult: ...
    async def discover_application(self, page: Page) -> str | None:
        """Site-ici ilan kesfi; desteklenmiyorsa None (Engine varsayilani)."""
        ...
    def submit_locator(self, page: Page) -> str | None:
        """Siteye ozel submit secici; None ise Engine varsayilan listesi.

        Salt locator dondurur, ASLA tiklamaz. Tiklama yalnizca Engine'de,
        confirmed=True + mod izniyle yapilir.
        """
        ...
    # submit() is intentionally ABSENT: submit lives only in the Engine,
    # behind an explicit confirmation flag.
