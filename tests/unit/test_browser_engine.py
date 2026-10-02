"""T1 characterization tests for the browser-agent refactor.

Pins the pre-refactor behavior against the new structure
(browser/site_adapters/* + BrowserAutomationEngine):
- verified answers fill, unverified answers land in skipped_unverified;
- CAPTCHA/login blockers stop automation without bypass;
- submit fires ONLY with submit=True + confirmed=True + FULL_AUTO mode;
- worker.py stays orchestration-only (< 150 lines).
"""
import asyncio
import concurrent.futures
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("playwright")

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "application_form.html"

from browser.site_adapters.base import FieldPlan  # noqa: E402
from browser.site_adapters.registry import register, resolve  # noqa: E402


def _load_engine():
    path = ROOT / "services" / "browser-agent" / "app" / "engine.py"
    spec = importlib.util.spec_from_file_location("careerflow_browser_engine", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_browser_engine"] = module
    spec.loader.exec_module(module)
    return module


_engine = _load_engine()
BrowserAutomationEngine = _engine.BrowserAutomationEngine


def _run(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _async_page(url):
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await (await browser.new_context()).new_page()
    await page.goto(url)
    return pw, browser, page


def _plan():
    return [
        FieldPlan("first_name", "First Name", "Ada", "text"),
        FieldPlan("email", "Email", "ada@example.com", "text"),
        FieldPlan("salary_expectation", "Salary expectation", None, "text"),
    ]


def test_registry_prefers_specific_adapter_with_generic_fallback():
    assert resolve("https://myorg.workable.com/j/123").name == "workable"
    assert resolve("https://jobs.ashbyhq.com/org/123").name == "generic"
    assert resolve("https://example.com/apply").name == "generic"


def test_register_adds_custom_adapter():
    from browser.site_adapters.generic import GenericAdapter

    class CustomAdapter(GenericAdapter):
        name = "custom-test"

        def matches(self, url: str) -> bool:
            return "custom-test.example" in url

    register(CustomAdapter())
    try:
        assert resolve("https://custom-test.example/apply").name == "custom-test"
        assert resolve("https://other.example/apply").name == "generic"
    finally:
        from browser.site_adapters import registry

        registry._ADAPTERS[:] = [a for a in registry._ADAPTERS if a.name != "custom-test"]


SIMPLE_FORM_URL = (
    "data:text/html,"
    "<html><body><form onsubmit='window.__submitted=true;return false;'>"
    "<input type='text' name='first_name'>"
    "<input type='email' name='email'>"
    "<input type='text' name='salary_expectation'>"
    "<script>window.__submitted=false;</script>"
    "</form></body></html>"
)


def test_fill_verified_and_skip_unverified():
    async def scenario():
        pw, browser, apage = await _async_page(SIMPLE_FORM_URL)
        try:
            from browser.site_adapters.generic import GenericAdapter

            result = await GenericAdapter().fill(apage, _plan())
            assert "first_name" in result.filled
            assert "email" in result.filled
            assert "salary_expectation" in result.skipped_unverified
            assert await apage.evaluate("window.__submitted") is False
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_verified_dom_values_written():
    async def scenario():
        pw, browser, apage = await _async_page(FIXTURE.as_uri())
        try:
            from browser.site_adapters.generic import GenericAdapter

            await GenericAdapter().fill(apage, _plan())
            assert await apage.locator("#first_name").input_value() == "Ada"
            assert await apage.locator("#salary_expectation").input_value() == ""
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_captcha_blocker_stops_without_bypass():
    async def scenario():
        pw, browser, apage = await _async_page(FIXTURE.as_uri())
        try:
            engine = BrowserAutomationEngine()
            result = await engine.run(FIXTURE.as_uri(), _plan())
            assert result.blocked_reason == "CAPTCHA"
            assert result.submitted is False
            assert result.filled == []
        finally:
            await browser.close()
            await pw.stop()

    _run(scenario())


def test_submit_requires_confirmation_and_full_auto(monkeypatch):
    from shared.config import settings

    async def attempt(submit, confirmed):
        engine = BrowserAutomationEngine()
        spy = AsyncMock(return_value=True)
        monkeypatch.setattr(engine, "_click_submit", spy)
        result = await engine.run(
            "https://example.com/apply", _plan(), submit=submit, confirmed=confirmed
        )
        return result, spy

    # No confirmation, no submit — even when explicitly requested.
    result, spy = _run(attempt(True, False))
    assert result.submitted is False
    spy.assert_not_called()

    # Confirmed but PREPARE mode — still no submit.
    result, spy = _run(attempt(True, True))
    assert result.submitted is False
    spy.assert_not_called()

    # Confirmed + FULL_AUTO + AUTO_SUBMIT — submit allowed.
    monkeypatch.setattr(settings, "AUTOMATION_MODE", "FULL_AUTO")
    monkeypatch.setattr(settings, "AUTO_SUBMIT", True)
    result, spy = _run(attempt(True, True))
    assert result.submitted is True
    spy.assert_called_once()


def test_build_plan_uses_verified_answers_only():
    from types import SimpleNamespace

    engine = BrowserAutomationEngine()
    questions = [
        SimpleNamespace(question_key="email", question_text="Email", question_type="email", id="q1"),
        SimpleNamespace(question_key="salary_expectation", question_text="Salary", question_type="text", id="q2"),
    ]
    answers = [
        SimpleNamespace(question_id="q1", answer_value={"value": "ada@example.com"}, is_verified=True),
        SimpleNamespace(question_id="q2", answer_value={"value": "99999"}, is_verified=False),
    ]
    plan = {f.key: f for f in engine.build_plan(questions, answers)}
    assert plan["email"].value == "ada@example.com"
    assert plan["salary_expectation"].value is None


def test_worker_is_orchestration_only():
    lines = (ROOT / "services" / "browser-agent" / "app" / "worker.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 150, f"worker.py must stay orchestration-only, has {len(lines)} lines"
