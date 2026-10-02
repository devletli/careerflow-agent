"""SiteAdapter + safety regression tests on local HTML fixtures.

Uses pytest-playwright (`page` fixture) and async Playwright over file://
URLs only: no internet, no external sites, no real applications. Covers the
refactored BrowserAutomationEngine / SiteAdapter / safety modules with the
production code paths.
"""
import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytest.importorskip("playwright")

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / "tests" / "fixtures" / "forms"


def _load_browser_package():
    """Loads services/browser-agent/app as an isolated package so its
    relative imports resolve without colliding with other `app` packages."""
    app_dir = ROOT / "services" / "browser-agent" / "app"
    pkg = ModuleType("careerflow_browser_app")
    pkg.__path__ = [str(app_dir)]
    sys.modules["careerflow_browser_app"] = pkg
    adapters = ModuleType("careerflow_browser_app.adapters")
    adapters.__path__ = [str(app_dir / "adapters")]
    sys.modules["careerflow_browser_app.adapters"] = adapters
    return {
        "generic": importlib.import_module("careerflow_browser_app.adapters.generic"),
        "registry": importlib.import_module("careerflow_browser_app.adapters.registry"),
        "safety": importlib.import_module("careerflow_browser_app.safety"),
        "engine": importlib.import_module("careerflow_browser_app.engine"),
    }


_mods = _load_browser_package()
GenericAdapter = _mods["generic"].GenericAdapter
resolve = _mods["registry"].resolve
assert_no_blockers = _mods["safety"].assert_no_blockers
HardStop = _mods["safety"].HardStop
BrowserAutomationEngine = _mods["engine"].BrowserAutomationEngine


async def _async_page(url):
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await (await browser.new_context()).new_page()
    await page.goto(url)
    return pw, browser, page


def _run(coro):
    # Sync wrapper: the pytest-playwright/pytest-asyncio hooks keep an event
    # loop running around tests, so async production code runs in a worker
    # thread with its own loop instead of asyncio.run() in this thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def test_registry_resolves_workable_then_generic():
    assert resolve("https://myorg.workable.com/j/123").name == "workable"
    assert resolve("https://jobs.ashbyhq.com/org/123").name == "generic"
    assert resolve("https://example.com/apply").name == "generic"


def test_simple_fixture_loads(page):
    """pytest-playwright page fixture over file:// (offline)."""
    page.goto((FORMS / "simple.html").as_uri())
    assert page.get_by_label("First Name").count() == 1
    assert page.get_by_label("Resume / CV (PDF)").count() == 1
    assert page.evaluate("window.__submitted") is False


def test_simple_form_fills_verified_fields():
    async def scenario():
        pw, browser, apage = await _async_page((FORMS / "simple.html").as_uri())
        try:
            result = await GenericAdapter().fill(apage, {"first_name": "Ada", "email": "ada@example.com"})
            assert "first_name" in result.filled
            assert "email" in result.filled
            assert await apage.locator("#first_name").input_value() == "Ada"
            assert await apage.evaluate("window.__submitted") is False
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_captcha_fixture_raises_hardstop():
    async def scenario():
        pw, browser, apage = await _async_page((FORMS / "with_captcha.html").as_uri())
        try:
            with pytest.raises(HardStop) as exc_info:
                await assert_no_blockers(apage)
            assert exc_info.value.reason == "captcha"
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_login_fixture_raises_hardstop():
    async def scenario():
        pw, browser, apage = await _async_page((FORMS / "with_login.html").as_uri())
        try:
            with pytest.raises(HardStop) as exc_info:
                await assert_no_blockers(apage)
            assert exc_info.value.reason == "login_wall"
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_custom_questions_never_guessed():
    async def scenario():
        pw, browser, apage = await _async_page((FORMS / "custom_questions.html").as_uri())
        try:
            result = await GenericAdapter().fill(apage, {"first_name": "Ada", "email": "ada@example.com"})
            assert "salary_expectation" in result.skipped  # no configured answer: untouched
            assert "anything_else" in result.skipped  # open-ended: untouched
            assert await apage.locator("#salary_expectation").input_value() == ""
            assert await apage.evaluate("window.__submitted") is False
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_prepare_mode_never_submits(monkeypatch):
    async def scenario():
        engine = BrowserAutomationEngine()
        submit_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(GenericAdapter, "submit", submit_spy)
        status, result = await engine.run_fill(
            application_url=(FORMS / "simple.html").as_uri(),
            app_id=uuid4(),
            answers={"first_name": "Ada"},
            submit=False,
        )
        assert status == "FILLED"
        assert result.submitted is False
        submit_spy.assert_not_called()

    _run(scenario())
