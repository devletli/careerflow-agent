"""Hotfix regression: desktop runner never writes password/OTP/hidden fields."""

import functools
import http.server
import importlib.util
import threading
from pathlib import Path

import pytest

FORMS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "forms"
RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("desktop_runner_hotfix", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def form_server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FORMS_DIR))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.mark.asyncio
async def test_never_fills_password_field(form_server, tmp_path):
    from playwright.async_api import async_playwright

    runner = _load_runner()
    profile = {"name": "Ada Lovelace", "email": "ada@example.com", "phone": "+1", "website": ""}
    context = {
        "application_id": "hotfix-pw",
        "application_url": f"{form_server}/login_wall.html",
        "verified_answers": {"username": "ada", "password": "s3cret", "first_name": "Ada"},
        "document_paths": {},
        "company": "Fixture",
        "title": "T",
    }
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await runner.fill_form(page, context, profile)
            assert await page.locator("#password").input_value() == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_never_fills_otp_field(form_server):
    from playwright.async_api import async_playwright

    runner = _load_runner()
    profile = {"name": "Ada Lovelace", "email": "ada@example.com", "phone": "", "website": ""}
    context = {
        "application_id": "hotfix-otp",
        "application_url": f"{form_server}/mfa.html",
        "verified_answers": {"mfa_code": "123456", "first_name": "Ada"},
        "document_paths": {},
        "company": "Fixture",
        "title": "T",
    }
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await runner.fill_form(page, context, profile)
            assert await page.locator("#mfa_code").input_value() == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_verified_text_field_still_fills(form_server):
    from playwright.async_api import async_playwright

    runner = _load_runner()
    profile = {"name": "Ada Lovelace", "email": "ada@example.com", "phone": "", "website": ""}
    context = {
        "application_id": "hotfix-ok",
        "application_url": f"{form_server}/with_captcha.html",
        "verified_answers": {"first_name": "Ada", "email": "ada@example.com"},
        "document_paths": {},
        "company": "Fixture",
        "title": "T",
    }
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await runner.fill_form(page, context, profile)
            assert await page.locator("#first_name").input_value() == "Ada"
        finally:
            await browser.close()
