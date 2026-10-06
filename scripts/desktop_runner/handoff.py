"""Human-handoff panel + wait loop (stdlib + playwright only).

The panel lives across navigations via context.add_init_script on every
page. Message text is assigned through textContent (never HTML injection).
The "Devam et" button is only a "re-check now" hint: the loop continues
solely when detect() reports the blocker is actually gone.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

PANEL_JS = """
(() => {
  if (document.getElementById('__cf_panel')) return;
  const p = document.createElement('div');
  p.id = '__cf_panel';
  p.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:340px;padding:12px 14px;'
    + 'background:#111827;color:#fff;font:13px/1.4 system-ui;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.35)';
  const m = document.createElement('div'); m.id = '__cf_msg';
  const b = document.createElement('button'); b.id = '__cf_btn'; b.textContent = 'Devam et';
  b.style.cssText = 'margin-top:8px;padding:6px 10px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer';
  b.onclick = () => { window.__cf_recheck = true; };
  p.append(m, b); document.documentElement.appendChild(p);
})();
"""


async def ensure_panel_script(ctx: BrowserContext) -> None:
    """Install the panel on every page of the context (survives navigation)."""
    await ctx.add_init_script(PANEL_JS)


async def show_panel(page: Page, message: str, *, button: bool = False) -> None:
    await page.evaluate(PANEL_JS)
    await page.evaluate(
        """([m, b]) => { document.getElementById('__cf_msg').textContent = m;
                        document.getElementById('__cf_btn').style.display = b ? 'inline-block' : 'none'; }""",
        [message, button],
    )


def active_page(ctx: BrowserContext, fallback: Page) -> Page:
    """The page the user actually works on (login popup / post-redirect)."""
    pages = [p for p in ctx.pages if not p.is_closed()]
    return pages[-1] if pages else fallback


async def wait_for_user(
    ctx: BrowserContext,
    page: Page,
    reason: str,
    detect: Callable[[Page], Awaitable[Optional[str]]],
    *,
    timeout_s: float,
    poll_s: float = 1.0,
) -> bool:
    """Wait until the blocker clears. True = cleared, False = timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        target = active_page(ctx, page)
        try:
            await show_panel(
                target, f"{reason} Çözünce otomatik devam ederim.", button=True
            )
            if await detect(target) is None:
                return True
            await target.evaluate("window.__cf_recheck = false")
        except PlaywrightError:
            pass  # context briefly lost during navigation
        await asyncio.sleep(poll_s)
    return False
