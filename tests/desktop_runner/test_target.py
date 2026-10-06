"""Faz 2: basvuru hedefi cozumleme (apply link, EMAIL_ONLY, NO_ONLINE_FORM)."""

import functools
import http.server
import importlib.util
import json
import re
import sys
import threading
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"
FORMS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "forms"
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


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


def _load_runner_main():
    for module_name in ("desktop_runner", "desktop_runner.diagnostics",
                        "desktop_runner.config", "desktop_runner.assisted",
                        "desktop_runner.documents", "desktop_runner.fields",
                        "desktop_runner.fill", "desktop_runner.blockers",
                        "desktop_runner.handoff", "desktop_runner.navigation",
                        "desktop_runner.target"):
        sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        path = SCRIPTS_DIR / "desktop_runner.py"
        spec = importlib.util.spec_from_file_location(
            "careerflow_desktop_runner_main", path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["careerflow_desktop_runner_main"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(SCRIPTS_DIR))
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
async def test_mailto_only_stops_with_email_only(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx, f"{form_server}/posting_mailto_only.html",
                PROFILE, {}, _settings(), {},
            )
            assert summary.target_kind == "email_only"
            assert summary.target_reason == "EMAIL_ONLY"
            assert summary.target_email == "bewerbung@fixture.example"
            assert summary.filled == []
            assert summary.timed_out is None
            # Yonlendirme yok, mail atilmadi: URL ayni sayfada.
            assert page.url.endswith("/posting_mailto_only.html")
            assert await page.evaluate("window.__submitted !== true") is True
            assert "bewerbung@fixture.example" in await page.content()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_formless_page_reports_no_online_form(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx, f"{form_server}/posting_no_form.html",
                PROFILE, {}, _settings(), {},
            )
            assert summary.target_kind == "no_form"
            assert summary.target_reason == "NO_ONLINE_FORM"
            assert summary.filled == []
            assert await page.evaluate("window.__submitted !== true") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_apply_link_followed_to_form(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx, f"{form_server}/posting_with_apply_link.html",
                PROFILE, {"first_name": "Ada"}, _settings(), {},
            )
            assert summary.target_kind == "moved"
            assert page.url.endswith("/simple.html")
            assert await page.locator("#first_name").input_value() == "Ada"
            assert await page.evaluate("window.__submitted") is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_opener_and_blocker_pages_stay_in_loop(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx, f"{form_server}/posting_with_opener.html",
                PROFILE, {"first_name": "Ada"}, _settings(), {},
            )
            assert summary.target_kind == "stay"
            assert await page.locator("#first_name").input_value() == "Ada"

            ctx2 = await browser.new_context()
            settings = _settings(handoff_timeout_seconds=0.4)
            page2, summary2 = await assisted.run_assisted(
                ctx2, f"{form_server}/login_wall.html",
                PROFILE, {}, settings, {},
            )
            assert summary2.target_kind == "stay"
            assert summary2.timed_out == "LOGIN"
            assert await page2.locator("#password").input_value() == ""
        finally:
            await browser.close()


def test_mailto_address_table():
    target = _load("target")
    assert target.mailto_address("mailto:a@b.de") == "a@b.de"
    assert target.mailto_address("mailto:a@b.de?subject=x&body=y") == "a@b.de"
    assert target.mailto_address("MAILTO:A@B.DE") == "A@B.DE"
    assert target.mailto_address("https://a.de/apply") is None
    assert target.mailto_address("mailto:not-an-address") is None
    assert target.mailto_address("") is None


def test_no_ats_conditionals_in_core_runner():
    ats_names = ("greenhouse", "lever", "workable", "ashby",
                 "smartrecruiters", "personio", "softgarden")
    pattern = re.compile(r"\bif\b.*(" + "|".join(ats_names) + r")", re.I)
    offenders = []
    paths = list(PACKAGE_DIR.glob("*.py")) + [SCRIPTS_DIR / "desktop_runner.py"]
    for path in paths:
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], f"cekirdek runner'da ATS kosulu: {offenders}"


def test_target_email_never_in_report():
    main = _load_runner_main()

    class Summary:
        ats = "ashby"
        filled = []
        unverified = []
        handoffs = 0
        timed_out = None
        target_kind = "email_only"
        target_reason = "EMAIL_ONLY"
        target_email = "bewerbung@fixture.example"

    report = main._summary_report("https://karriere.example/stelle/1", Summary())
    text = json.dumps(report, ensure_ascii=False)
    assert "bewerbung@fixture.example" not in text
    assert report["ats"] == "ashby"
    assert any(step.get("reason") == "EMAIL_ONLY"
               for step in report["steps"])
