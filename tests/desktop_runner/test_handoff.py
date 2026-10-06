"""Handoff panel: textContent messaging, re-check flag, wait loop."""

import importlib.util
import sys
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"


def _load(name):
    for module_name in ("desktop_runner", f"desktop_runner.{name}"):
        sys.modules.pop(module_name, None)
    sys.path.insert(0, str(PACKAGE_DIR.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            f"desktop_runner.{name}", PACKAGE_DIR / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"desktop_runner.{name}"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(PACKAGE_DIR.parent))
        except ValueError:
            pass


@pytest.mark.asyncio
async def test_panel_uses_text_not_html():
    from playwright.async_api import async_playwright

    handoff = _load("handoff")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content("<html><body><h1>Form</h1></body></html>")
            await handoff.show_panel(page, "<b>kötü</b> & mesaj", button=True)
            assert await page.locator("#__cf_panel").count() == 1
            assert await page.locator("#__cf_msg").text_content() == "<b>kötü</b> & mesaj"
            assert await page.locator("#__cf_msg b").count() == 0
            await page.locator("#__cf_btn").click()
            assert await page.evaluate("window.__cf_recheck") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_wait_returns_true_when_blocker_clears():
    from playwright.async_api import async_playwright

    handoff = _load("handoff")
    calls = {"n": 0}

    async def detect(page):
        calls["n"] += 1
        return None if calls["n"] >= 3 else "CAPTCHA"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.set_content("<html><body></body></html>")
            assert await handoff.wait_for_user(ctx, page, "CAPTCHA bekleniyor.", detect, timeout_s=10, poll_s=0.05) is True
            assert calls["n"] >= 3
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_wait_times_out_when_blocker_persists():
    from playwright.async_api import async_playwright

    handoff = _load("handoff")

    async def detect(page):
        return "LOGIN"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.set_content("<html><body></body></html>")
            assert await handoff.wait_for_user(ctx, page, "Giriş bekleniyor.", detect, timeout_s=0.3, poll_s=0.05) is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_active_page_follows_popup():
    from playwright.async_api import async_playwright

    handoff = _load("handoff")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            first = await ctx.new_page()
            await first.set_content("<html><body>form</body></html>")
            second = await ctx.new_page()
            await second.set_content("<html><body>login popup</body></html>")
            assert handoff.active_page(ctx, first) == second
        finally:
            await browser.close()
