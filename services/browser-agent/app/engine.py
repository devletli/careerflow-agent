"""BrowserAutomationEngine: Playwright context, safety gates, fill orchestration.

Behavior is identical to the previous inline worker implementation; only the
structure changed. Safety stop-conditions (CAPTCHA/login/MFA) return BLOCKED
and are never bypassed. Submit only happens when the caller explicitly passes
submit=True (confirmed flow).
"""
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
from uuid import UUID

from shared.config import settings

from .adapters.base import FillResult
from .adapters.registry import resolve
from .safety import HardStop, assert_no_blockers

logger = logging.getLogger(__name__)


class BrowserAutomationEngine:
    def __init__(self):
        pass

    async def run_fill(
        self,
        application_url: str,
        app_id: UUID,
        answers: Dict[str, Any],
        submit: bool = False,
        on_submitting: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> Tuple[str, FillResult]:
        """Navigates, fills via the resolved SiteAdapter. Returns (status, result).

        Status is one of FILLED | SUBMITTED | BLOCKED | FAILED.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Cannot fill forms.")
            return "FAILED", FillResult()

        adapter = resolve(application_url)
        logger.info(f"Using '{adapter.name}' site adapter for {application_url}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=settings.BROWSER_HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            try:
                logger.info(f"Navigating to {application_url}")
                await page.goto(application_url, wait_until="networkidle", timeout=30000)

                try:
                    await assert_no_blockers(page)
                except HardStop as stop:
                    logger.warning(f"{stop.reason} detected on {application_url}")
                    await browser.close()
                    return "BLOCKED", FillResult(needs_human=[stop.reason])

                result = await adapter.fill(page, answers)
                logger.info(
                    f"Filled {len(result.filled)} fields, "
                    f"skipped {len(result.skipped)}, "
                    f"needs_human {len(result.needs_human)}"
                )

                screenshot_path = f"/app/browser-traces/app_{app_id}_filled.png"
                try:
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logger.info(f"Screenshot saved: {screenshot_path}")
                except Exception as ss_err:
                    logger.debug(f"Screenshot failed (non-fatal): {ss_err}")

                if submit:
                    if on_submitting is not None:
                        await on_submitting()
                    if not await adapter.submit(page):
                        return "FAILED", result
                    result.submitted = True
                    return "SUBMITTED", result

                return "FILLED", result

            except Exception as nav_err:
                logger.error(f"Navigation/fill error: {nav_err}")
                return "FAILED", FillResult()
            finally:
                await browser.close()
