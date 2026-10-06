"""Assisted loop: fill -> hand off on blocker -> wait -> continue.

Adapter-free by design: it reuses the existing verified_answers matching
(fields.py) and wraps the fill/wait cycle around it. No status reporting in
v1, no submit clicking, no credential writing.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import BrowserContext, Locator, Page

from desktop_runner.blockers import detect_blocker
from desktop_runner.config import DesktopSettings
from desktop_runner.documents import attach_files
from desktop_runner.fields import answer_for_field, normalized, standard_answers
from desktop_runner.fill import (
    FILLED,
    mark_unverified,
    set_checkable,
    set_select,
)
from desktop_runner.fill import (
    fill_field as type_field,
)
from desktop_runner.handoff import (
    active_page,
    ensure_panel_script,
    show_panel,
    wait_for_user,
)
from desktop_runner.navigation import (
    NEXT_RX,
    click_next,
    dismiss_cookie_banner,
    is_submit_label,
)

REASONS = {
    "CAPTCHA": "CAPTCHA bekleniyor.",
    "LOGIN": "Giriş bekleniyor.",
    "MFA": "Doğrulama kodu bekleniyor.",
}

MAX_STEPS = 12

SKIP_TYPES = {
    "file",
    "checkbox",
    "radio",
    "submit",
    "button",
    "password",
    "hidden",
    "image",
    "reset",
}

CREDENTIAL_AUTOCOMPLETE = {"one-time-code", "current-password", "new-password"}
TRUTHY = {"yes", "true", "1", "checked", "on", "ja"}


@dataclass
class StepResult:
    filled: list[str] = field(default_factory=list)
    unverified_required: list[str] = field(default_factory=list)
    unverified_locators: list[Locator] = field(default_factory=list)


@dataclass
class AssistSummary:
    filled: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    handoffs: int = 0
    timed_out: str | None = None


async def _field_key(field: Locator) -> str:
    parts = []
    for attr in ("name", "id", "autocomplete", "placeholder", "aria-label"):
        try:
            parts.append(await field.get_attribute(attr))
        except Exception:
            parts.append(None)
    return normalized(" ".join(filter(None, parts)))


async def _is_required(field: Locator) -> bool:
    try:
        return bool(
            await field.evaluate(
                "(el) => el.required === true || el.getAttribute('aria-required') === 'true'"
            )
        )
    except Exception:
        return False


async def _current_value(field: Locator) -> str:
    try:
        return (await field.input_value()).strip()
    except Exception:
        return ""


def _matches_checkable(field_value_attr: str | None, verified: object) -> bool:
    text = str(verified).strip().lower()
    if not text:
        return False
    if text in TRUTHY:
        return True
    attr = (field_value_attr or "").lower()
    return bool(attr) and (text == attr or text in attr or attr in text)


async def inspect_and_fill(page: Page, answers: dict, delay_ms: int) -> StepResult:
    """Fill one visible step from verified answers; record human work."""
    result = StepResult()

    fields = page.locator("input:not([type='hidden']), textarea")
    for index in range(await fields.count()):
        loc = fields.nth(index)
        try:
            if not await loc.is_visible() or not await loc.is_enabled():
                continue
        except Exception:
            continue
        try:
            tag = (await loc.evaluate("(el) => el.tagName")).lower()
        except Exception:
            continue
        if tag == "textarea":
            input_type = "textarea"
        else:
            try:
                input_type = ((await loc.get_attribute("type")) or "text").lower()
            except Exception:
                input_type = "text"
        if input_type in SKIP_TYPES:
            continue
        try:
            autocomplete = ((await loc.get_attribute("autocomplete")) or "").lower().strip()
        except Exception:
            autocomplete = ""
        key = await _field_key(loc)
        required = await _is_required(loc)
        if autocomplete in CREDENTIAL_AUTOCOMPLETE:
            if required and not await _current_value(loc):
                result.unverified_required.append(key or "credential")
                result.unverified_locators.append(loc)
            continue
        value = answer_for_field(key, answers)
        if value is not None and str(value).strip():
            try:
                if await type_field(loc, str(value), delay_ms) == FILLED:
                    result.filled.append(key)
            except RuntimeError:
                continue
        elif not await _current_value(loc):
            if required:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)

    for index in range(await page.locator("select").count()):
        loc = page.locator("select").nth(index)
        try:
            if not await loc.is_visible() or not await loc.is_enabled():
                continue
        except Exception:
            continue
        key = await _field_key(loc)
        required = await _is_required(loc)
        value = answer_for_field(key, answers)
        if value is not None and str(value).strip():
            if await set_select(loc, str(value)) == FILLED:
                result.filled.append(key)
        else:
            try:
                selected = await loc.evaluate(
                    "(el) => { const s = Array.from(el.selectedOptions).map(o => o.value);"
                    " return el.multiple ? s : (s[0] ?? ''); }"
                )
            except Exception:
                selected = ""
            has_selection = (
                any(str(v).strip() for v in selected)
                if isinstance(selected, list)
                else bool(str(selected).strip())
            )
            if not has_selection and required:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)

    for box_type in ("checkbox", "radio"):
        boxes = page.locator(f"input[type='{box_type}']")
        for index in range(await boxes.count()):
            loc = boxes.nth(index)
            try:
                if not await loc.is_visible() or not await loc.is_enabled():
                    continue
                checked = await loc.is_checked()
            except Exception:
                continue
            if checked:
                continue
            key = await _field_key(loc)
            required = await _is_required(loc)
            value = answer_for_field(key, answers)
            matched = False
            if value is not None and str(value).strip():
                try:
                    attr = await loc.get_attribute("value")
                except Exception:
                    attr = None
                matched = _matches_checkable(attr, value)
            if matched:
                if await set_checkable(loc, True) == FILLED:
                    result.filled.append(key)
            elif required:
                result.unverified_required.append(key)
                result.unverified_locators.append(loc)

    return result


async def looks_like_application_form(page: Page, app_url: str) -> bool:
    """True when the page plausibly hosts the application form."""
    try:
        current = urllib.parse.urlparse(page.url)
        want = urllib.parse.urlparse(app_url)
        if (
            current.hostname
            and want.hostname
            and current.hostname.lower() != want.hostname.lower()
        ):
            return False
    except Exception:
        pass
    try:
        if await page.locator("input[type=password]:visible").count():
            return False  # login wall, not the form
        if await page.locator("input[type='file']:visible").count():
            return True
        for btn in await page.get_by_role("button").all():
            try:
                name = (await btn.inner_text()).strip()
            except Exception:
                continue
            if name and is_submit_label(name):
                try:
                    if await btn.is_visible():
                        return True
                except Exception:
                    continue
        if await page.locator("input[required]:visible").count():
            return True
    except Exception:
        return False
    return False


async def is_final_step(page: Page) -> bool:
    """True when no clickable Next-type button remains."""
    try:
        for btn in await page.get_by_role("button").all():
            try:
                name = (await btn.inner_text()).strip()
            except Exception:
                continue
            if not name or is_submit_label(name):
                continue
            try:
                if (
                    NEXT_RX.match(name)
                    and await btn.is_visible()
                    and await btn.is_enabled()
                ):
                    return False
            except Exception:
                continue
    except Exception:
        return True
    return True


def summary_text(filled: int, unverified: int) -> str:
    if unverified:
        return f"{filled} alan dolduruldu; sarı alanları sen doldur, sonra gönder."
    return f"{filled} alan dolduruldu; formu gözden geçirip gönder."


async def run_assisted(
    ctx: BrowserContext,
    app_url: str,
    profile: dict,
    verified_answers: dict,
    settings: DesktopSettings,
    prepared: dict[str, Path],
) -> tuple[Page, AssistSummary]:
    """Fill, hand off on blockers, wait, and continue across steps."""
    answers = standard_answers(profile)
    answers.update(verified_answers or {})

    await ensure_panel_script(ctx)
    page = await ctx.new_page()
    await page.goto(app_url, wait_until="domcontentloaded", timeout=45_000)

    summary = AssistSummary()
    for _ in range(MAX_STEPS):
        blocker = await detect_blocker(page)
        if blocker:
            summary.handoffs += 1
            ok = await wait_for_user(
                ctx,
                page,
                REASONS[blocker],
                detect_blocker,
                timeout_s=settings.handoff_timeout_seconds,
            )
            if not ok:
                summary.timed_out = blocker
                break
            page = active_page(ctx, page)
            if not await looks_like_application_form(page, app_url):
                await page.goto(app_url, wait_until="domcontentloaded", timeout=45_000)
            continue
        await dismiss_cookie_banner(page)
        step = await inspect_and_fill(page, answers, settings.type_delay_ms)
        await attach_files(page, prepared)
        await mark_unverified(page, step.unverified_locators)
        summary.filled.extend(step.filled)
        summary.unverified.extend(step.unverified_required)
        if step.unverified_required or await is_final_step(page):
            break
        if not settings.auto_next or not await click_next(page):
            break
    await show_panel(page, summary_text(len(summary.filled), len(summary.unverified)))
    return page, summary
