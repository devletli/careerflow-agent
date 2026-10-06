"""Assisted loop: fill, handoff-wait-continue, step gating, summary panel."""

import functools
import http.server
import importlib.util
import sys
import threading
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"
FORMS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "forms"


def _load(name):
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


@pytest.fixture(scope="module")
def form_server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FORMS_DIR))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _settings(**overrides):
    config = _load("config")
    base = {
        "handoff_timeout_seconds": 15.0,
        "auto_next": True,
        "type_delay_ms": 1,
        "browser_channel": "chromium",
    }
    base.update(overrides)
    return config.DesktopSettings(**base)


PROFILE = {"name": "Ada Lovelace", "email": "ada@example.com", "phone": "+49 170", "website": ""}


@pytest.mark.asyncio
async def test_fills_simple_form_and_leaves_submit_to_human(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    settings = _settings()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx,
                f"{form_server}/simple.html",
                PROFILE,
                {"first_name": "Ada"},
                settings,
                {},
            )
            assert await page.locator("#first_name").input_value() == "Ada"
            assert await page.locator("#email").input_value() == "ada@example.com"
            assert await page.evaluate("window.__submitted") is False
            assert summary.timed_out is None
            assert summary.handoffs == 0
            assert "__cf_panel" in await page.content()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_waits_for_clearing_captcha_then_continues(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    settings = _settings()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx,
                f"{form_server}/desktop_captcha_resolves.html",
                PROFILE,
                {"first_name": "Ada"},
                settings,
                {},
            )
            assert summary.handoffs == 1
            assert summary.timed_out is None
            assert await page.locator("#first_name").input_value() == "Ada"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_persistent_blocker_times_out_without_writing(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    settings = _settings(handoff_timeout_seconds=0.4)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx,
                f"{form_server}/login_wall.html",
                PROFILE,
                {"username": "ada", "password": "s3cret"},
                settings,
                {},
            )
            assert summary.timed_out == "LOGIN"
            assert await page.locator("#password").input_value() == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_two_step_advances_only_when_required_verified(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    settings = _settings()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx,
                f"{form_server}/desktop_two_step.html",
                PROFILE,
                {"first_name": "Ada"},
                settings,
                {},
            )
            assert await page.evaluate("window.__advanced") is True
            assert await page.locator("#phone").input_value() == "+49 170"
            assert await page.evaluate("window.__submitted") is False
            assert summary.timed_out is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_opener_reveals_posting_form_then_fills_without_submit(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    settings = _settings()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx,
                f"{form_server}/posting_with_opener.html",
                PROFILE,
                {"first_name": "Ada"},
                settings,
                {},
            )
            assert await page.evaluate("window.__opened") is True
            assert await page.locator("#first_name").input_value() == "Ada"
            assert await page.evaluate("window.__submitted !== true") is True
            assert summary.timed_out is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_two_step_stops_when_required_unverified(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    settings = _settings()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx,
                f"{form_server}/desktop_two_step.html",
                {"name": "", "email": "", "phone": "", "website": ""},
                {},
                settings,
                {},
            )
            assert await page.evaluate("window.__advanced") is False
            assert len(summary.unverified) > 0
        finally:
            await browser.close()
