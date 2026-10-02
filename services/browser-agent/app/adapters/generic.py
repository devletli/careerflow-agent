"""Generic ATS form adapter: accessible-locator-first field filling.

This is the previous inline worker logic, extracted without behavior change:
fill visible/enabled inputs and textareas whose name/id/placeholder matches a
verified answer key. Password and CAPTCHA-like controls are never touched and
are reported as needing a human.
"""
import logging
from typing import TYPE_CHECKING, Any, Dict

from .base import FillResult, SiteAdapter

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Apply')",
    "button:has-text('Send Application')",
]

PROTECTED_HINTS = ("captcha", "recaptcha", "hcaptcha", "robot", "password")


class GenericAdapter(SiteAdapter):
    name = "generic"

    @classmethod
    def matches(cls, url: str) -> bool:
        return True

    def _lookup(self, answers: Dict[str, Any], key: str):
        for map_key, map_val in answers.items():
            if map_key.lower() in key or key in map_key.lower():
                return map_val
        return None

    async def fill(self, page: "Page", answers: Dict[str, Any]) -> FillResult:
        result = FillResult()
        # Defense in depth: report protection controls as needing a human
        # (safety.assert_no_blockers normally stops before this point).
        for control in await page.query_selector_all(
            "input[type='password'], [data-sitekey], iframe[src*='captcha']"
        ):
            try:
                name = (await control.get_attribute("name") or await control.get_attribute("id") or "protection-control")
                result.needs_human.append(name)
            except Exception:
                pass
        inputs = await page.query_selector_all(
            "input[type='text'], input[type='email'], input[type='tel'], input:not([type])"
        )
        for inp in inputs:
            try:
                name = await inp.get_attribute("name") or ""
                inp_id = await inp.get_attribute("id") or ""
                placeholder = await inp.get_attribute("placeholder") or ""
                key = (name or inp_id or placeholder).lower().replace("-", "_").replace(" ", "_")
                if not key:
                    continue
                if any(hint in key for hint in PROTECTED_HINTS):
                    result.needs_human.append(key)
                    continue
                value = self._lookup(answers, key)
                if value is not None and str(value).strip():
                    if await inp.is_visible() and await inp.is_enabled():
                        await inp.click()
                        await inp.fill(str(value))
                        result.filled.append(key)
                        logger.debug(f"Filled input '{key}'")
                    else:
                        result.skipped.append(key)
                else:
                    result.skipped.append(key)
            except Exception as field_err:
                logger.debug(f"Skipping field fill error: {field_err}")

        for ta in await page.query_selector_all("textarea"):
            try:
                name = await ta.get_attribute("name") or ""
                ta_id = await ta.get_attribute("id") or ""
                key = (name or ta_id).lower().replace("-", "_")
                value = answers.get(key) or answers.get(name.lower())
                if value and await ta.is_visible():
                    await ta.fill(str(value))
                    result.filled.append(key or name.lower())
                else:
                    result.skipped.append(key or name.lower())
            except Exception:
                pass
        return result

    async def submit(self, page: "Page") -> bool:
        try:
            for selector in SUBMIT_SELECTORS:
                button = await page.query_selector(selector)
                if button and await button.is_visible() and await button.is_enabled():
                    await button.click()
                    await page.wait_for_timeout(3000)
                    return True
            logger.warning("No submit button found")
        except Exception as exc:
            logger.error(f"Submit failed: {exc}")
        return False
