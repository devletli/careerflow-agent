"""Visible, non-destructive field filling (stdlib + playwright only).

Rules (never relaxed):
- Never write into password inputs (RuntimeError) or credential/OTP
  autocomplete fields (skipped, never written).
- Never overwrite a pre-filled/pre-selected value belonging to the user
  or the page ("skipped_prefilled").
- Green outline = runner filled it; yellow outline = human must fill it.
"""
from __future__ import annotations

from typing import Iterable

from playwright.async_api import Locator, Page

FILLED = "filled"
SKIPPED_PREFILLED = "skipped_prefilled"
SKIPPED_CREDENTIAL = "skipped_credential"

GREEN = "#22c55e"
YELLOW = "#eab308"
RED = "#ef4444"

_CREDENTIAL_AUTOCOMPLETE = {"one-time-code", "current-password", "new-password"}


async def highlight(loc: Locator, color: str) -> None:
    await loc.evaluate(
        "(el, c) => { el.style.outline = `3px solid ${c}`; el.style.outlineOffset = '2px'; }",
        color,
    )


async def _is_credential_field(loc: Locator) -> bool:
    try:
        field_type = ((await loc.get_attribute("type")) or "").lower()
    except Exception:
        field_type = ""
    if field_type == "password":
        raise RuntimeError("password alanına yazmak yasak")
    try:
        autocomplete = ((await loc.get_attribute("autocomplete")) or "").lower().strip()
    except Exception:
        autocomplete = ""
    return autocomplete in _CREDENTIAL_AUTOCOMPLETE


async def fill_field(loc: Locator, value: str, delay_ms: int) -> str:
    """Type into an empty text-like field; never overwrite existing content."""
    if await _is_credential_field(loc):
        return SKIPPED_CREDENTIAL
    await loc.scroll_into_view_if_needed()
    try:
        current = await loc.input_value()
    except Exception:
        current = ""
    if current.strip():
        return SKIPPED_PREFILLED
    await loc.press_sequentially(value, delay=delay_ms)
    await highlight(loc, GREEN)
    return FILLED


async def set_select(loc: Locator, value: str) -> str:
    """Select an option only when nothing is selected yet."""
    if await _is_credential_field(loc):
        return SKIPPED_CREDENTIAL
    await loc.scroll_into_view_if_needed()
    try:
        selected = await loc.evaluate(
            """(el) => {
                const sel = Array.from(el.selectedOptions).map(o => o.value);
                return el.multiple ? sel : (sel[0] ?? '');
            }"""
        )
    except Exception:
        selected = ""
    if isinstance(selected, list):
        if any(str(v).strip() for v in selected):
            return SKIPPED_PREFILLED
    elif str(selected).strip():
        return SKIPPED_PREFILLED
    try:
        await loc.select_option(label=value)
    except Exception:
        await loc.select_option(value=value)
    await highlight(loc, GREEN)
    return FILLED


async def set_checkable(loc: Locator, checked: bool) -> str:
    """Check/uncheck a checkbox/radio only when its state is still untouched."""
    await loc.scroll_into_view_if_needed()
    try:
        is_checked = await loc.is_checked()
    except Exception:
        return SKIPPED_PREFILLED
    if is_checked:
        return SKIPPED_PREFILLED
    if checked:
        await loc.check()
    else:
        await loc.uncheck()
    await highlight(loc, GREEN)
    return FILLED


async def mark_unverified(page: Page, locators: Iterable[Locator]) -> None:
    """Outline fields the human must fill themselves (yellow)."""
    for loc in locators:
        try:
            await highlight(loc, YELLOW)
        except Exception:
            continue
