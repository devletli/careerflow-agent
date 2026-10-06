"""Desktop-only blocker detection (visible challenges only).

Deliberately separate from browser.site_adapters.generic.detect_blockers
(which the headless engine keeps using untouched):
- No full-page text substring scanning (too many false positives).
- The invisible reCAPTCHA badge (iframe inside .grecaptcha-badge) is NEVER
  a blocker; otherwise the runner would wait forever on protected pages.
- A visible challenge/checkbox counts as CAPTCHA only while its response
  token is EMPTY; a solved CAPTCHA (token filled) is not a blocker.
- LOGIN = visible password field. MFA = visible one-time-code field.
"""
from __future__ import annotations

from playwright.async_api import Page

CHALLENGE_IFRAME_SELECTORS = [
    "iframe[src*='recaptcha/api2/bframe']",
    "iframe[src*='hcaptcha.com'][src*='challenge']",
    "iframe[src*='challenges.cloudflare.com']",
]

CHECKBOX_SELECTORS = [
    ".g-recaptcha",
    ".h-captcha",
]

TOKEN_SELECTORS = [
    "textarea[name='g-recaptcha-response']",
    "textarea[name='h-captcha-response']",
    "input[name='cf-turnstile-response']",
]

_BADGE_ANCESTOR_JS = "(el) => !el.closest('.grecaptcha-badge')"


async def _visible_outside_badge(page: Page, selector: str) -> bool:
    loc = page.locator(selector).first
    try:
        if not await loc.is_visible():
            return False
    except Exception:
        return False
    try:
        handle = await loc.element_handle()
        if handle is None:
            return False
        return await handle.evaluate(_BADGE_ANCESTOR_JS)
    except Exception:
        return False


async def _captcha_token_filled(page: Page) -> bool:
    for selector in TOKEN_SELECTORS:
        loc = page.locator(selector).first
        try:
            if await loc.count() and (await loc.input_value()).strip():
                return True
        except Exception:
            continue
    return False


async def _visible_captcha_challenge(page: Page) -> bool:
    for selector in CHALLENGE_IFRAME_SELECTORS + CHECKBOX_SELECTORS:
        if await _visible_outside_badge(page, selector):
            return True
    return False


async def detect_blocker(page: Page) -> str | None:
    """Return 'CAPTCHA' | 'LOGIN' | 'MFA', or None when no blocker is visible."""
    if await _visible_captcha_challenge(page):
        if not await _captcha_token_filled(page):
            return "CAPTCHA"
        return None
    if await page.locator("input[type=password]:visible").count():
        return "LOGIN"
    if await page.locator("input[autocomplete='one-time-code']:visible").count():
        return "MFA"
    return None
