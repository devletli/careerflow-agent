"""Desktop blocker detection: visible challenges only, badge/solved never block."""

import functools
import http.server
import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"
FORMS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "forms"


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


@pytest.fixture(scope="module")
def form_server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FORMS_DIR))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page_name,expected",
    [
        ("desktop_badge_only.html", None),
        ("desktop_captcha_solved.html", None),
        ("with_captcha.html", "CAPTCHA"),
        ("with_login.html", "LOGIN"),
        ("mfa.html", "MFA"),
    ],
)
async def test_detect_blocker_matrix(form_server, page_name, expected):
    from playwright.async_api import async_playwright

    blockers = _load("blockers")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/{page_name}")
            assert await blockers.detect_blocker(page) == expected
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_challenge_clearing_unblocks(form_server):
    from playwright.async_api import async_playwright

    blockers = _load("blockers")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/desktop_captcha_resolves.html")
            assert await blockers.detect_blocker(page) == "CAPTCHA"
            deadline = time.monotonic() + 10
            seen_clear = False
            while time.monotonic() < deadline:
                if await blockers.detect_blocker(page) is None:
                    seen_clear = True
                    break
                await page.wait_for_timeout(200)
            assert seen_clear is True
        finally:
            await browser.close()


def test_no_content_substring_scanning():
    source = (PACKAGE_DIR / "blockers.py").read_text(encoding="utf-8")
    assert ".content(" not in source
    assert "inner_text" not in source
