"""Multi-step navigation + cookie-banner helper (stdlib + playwright only).

Submit-type buttons ("Gönder/Absenden/Apply/Submit") are NEVER clicked here;
submission stays exclusively in the confirmed dashboard flow. Only "Next"-
type buttons advance a multi-step form. Cookie banners: only a
reject/necessary-only button is ever clicked; "accept all" never is.
"""
from __future__ import annotations

import re

from playwright.async_api import Page

SUBMIT_RX = re.compile(
    r"submit|send application|apply now|absenden|bewerbung (abschicken|absenden)|"
    r"jetzt bewerben|ba.l?vuruyu g.nder|g.nder",
    re.I,
)

NEXT_RX = re.compile(
    r"^(next|continue|weiter|n.chster schritt|devam|ileri)$", re.I
)

REJECT_RX = re.compile(
    r"reject|decline|only necessary|necessary only|essential only|"
    r"strictly necessary|nur notwendige|alle ablehnen|ablehnen|"
    r"yaln.zca gerekli|sadece gerekli|reddet|zorunlu",
    re.I,
)

ACCEPT_ALL_RX = re.compile(
    r"accept all|alle akzeptieren|t.m.n. kabul et", re.I
)


def is_submit_label(name: str) -> bool:
    return SUBMIT_RX.search(name) is not None


async def click_next(page: Page) -> bool:
    """Click a visible+enabled Next-type button (never a submit button)."""
    for btn in await page.get_by_role("button").all():
        try:
            name = (await btn.inner_text()).strip()
        except Exception:
            continue
        if not name or is_submit_label(name):
            continue
        try:
            if NEXT_RX.match(name) and await btn.is_visible() and await btn.is_enabled():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")
                return True
        except Exception:
            continue
    return False


async def dismiss_cookie_banner(page: Page) -> bool:
    """Click reject/necessary-only when present. Never clicks accept-all."""
    for btn in await page.get_by_role("button").all():
        try:
            name = (await btn.inner_text()).strip()
        except Exception:
            continue
        if not name or ACCEPT_ALL_RX.search(name):
            continue
        if not REJECT_RX.search(name):
            continue
        # A label matching both (e.g. "reject optional") is still safe:
        # it is not an accept-all label (checked above).
        try:
            if await btn.is_visible() and await btn.is_enabled():
                await btn.click()
                return True
        except Exception:
            continue
    return False
