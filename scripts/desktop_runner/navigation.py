"""Multi-step navigation + cookie-banner helper (stdlib + playwright only).

Submit-type buttons ("Gönder/Absenden/Apply Now/Submit") are NEVER clicked
here; submission stays exclusively in the confirmed dashboard flow. Only
"Next"-type buttons advance a multi-step form, and only narrow form-opener
labels ("Apply for this job") reveal a hidden form on posting pages.
Cookie banners: only a reject/necessary-only button is ever clicked;
"accept all" never is.
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

# Form openers: labels that reveal the application form on a posting page
# (Ashby/Greenhouse/Lever style). Deliberately narrow; anything matching
# SUBMIT_RX stays forbidden and is checked first in click_form_opener.
FORM_OPENER_RX = re.compile(
    r"^(apply for this (job|position)|apply to this job|"
    r"(auf|f.r) diese stelle bewerben|"
    r"bu (ilana|pozisyona) ba.l?vur)$",
    re.I,
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


async def wait_for_content(page: Page, timeout_ms: int = 15_000) -> bool:
    """Sayfa içeriği (en az bir görünür düğme) belirene kadar bekler.

    Yönlendirme sonrası DOM henüz boşken tarama yapılmasın diye; süre
    dolarsa False döner (akış aynen devam eder, beklemez).
    """
    try:
        await page.get_by_role("button").first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


async def click_form_opener(page: Page) -> bool:
    """Click a form-opening button (never a submit button).

    Only for posting pages: reveals the hidden application form so the
    assisted loop can fill it. Submit labels are skipped even if they
    also matched the opener pattern.
    """
    for btn in await page.get_by_role("button").all():
        try:
            name = (await btn.inner_text()).strip()
        except Exception:
            continue
        if not name or is_submit_label(name):
            continue
        try:
            if FORM_OPENER_RX.match(name) and await btn.is_visible() and await btn.is_enabled():
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
