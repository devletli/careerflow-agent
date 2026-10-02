"""Safety stop-conditions for browser automation.

Any CAPTCHA, login wall, or MFA indicator raises HardStop. The caller maps
HardStop to a BLOCKED application status — these challenges are never
bypassed or worked around.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class HardStop(Exception):
    """Raised when automation must stop for a human (captcha/login/MFA)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "[data-sitekey]",
]

CAPTCHA_TEXT_INDICATORS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "security check",
    "prove you're human",
    "robot",
    "cloudflare",
    "access denied",
]

LOGIN_TEXT_INDICATORS = [
    "sign in to continue",
    "please log in",
    "create an account to apply",
]


async def assert_no_blockers(page: "Page") -> None:
    """Raises HardStop('captcha' | 'login_wall') when automation must stop."""
    for selector in CAPTCHA_SELECTORS:
        if await page.locator(selector).count():
            raise HardStop("captcha")
    page_text = (await page.content()).lower()
    if any(indicator in page_text for indicator in CAPTCHA_TEXT_INDICATORS):
        raise HardStop("captcha")
    if await page.locator("input[type=password]").count():
        raise HardStop("login_wall")
    if any(indicator in page_text for indicator in LOGIN_TEXT_INDICATORS):
        raise HardStop("login_wall")
