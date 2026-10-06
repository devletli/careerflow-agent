"""Navigation: Next advances, Submit never clicked, cookies reject-only."""

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
async def test_click_next_skips_submit_and_clicks_next():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<button id='s' onclick=\"window.__s=true\">Submit application</button>"
                "<button id='n' onclick=\"window.__n=true\">Weiter</button>"
                "</body></html>"
            )
            assert await nav.click_next(page) is True
            assert await page.evaluate("window.__n") is True
            assert await page.evaluate("window.__s !== true") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_click_next_returns_false_on_submit_only():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<button id='s' onclick=\"window.__s=true\">Başvuruyu Gönder</button>"
                "</body></html>"
            )
            assert await nav.click_next(page) is False
            assert await page.evaluate("window.__s !== true") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_cookie_banner_clicks_reject_never_accept():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<div role='dialog'>"
                "<button id='a' onclick=\"window.__a=true\">Tümünü kabul et</button>"
                "<button id='r' onclick=\"window.__r=true\">Yalnızca gerekli</button>"
                "</div></body></html>"
            )
            assert await nav.dismiss_cookie_banner(page) is True
            assert await page.evaluate("window.__r") is True
            assert await page.evaluate("window.__a !== true") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_cookie_banner_leaves_accept_only_to_human():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<button id='a' onclick=\"window.__a=true\">Accept all</button>"
                "</body></html>"
            )
            assert await nav.dismiss_cookie_banner(page) is False
            assert await page.evaluate("window.__a !== true") is True
        finally:
            await browser.close()


def test_submit_labels_classified():
    nav = _load("navigation")
    for label in ("Submit", "Apply Now", "Absenden", "Jetzt bewerben", "Gönder"):
        assert nav.is_submit_label(label) is True
    for label in ("Next", "Weiter", "Devam", "İleri"):
        assert nav.is_submit_label(label) is False


@pytest.mark.asyncio
async def test_click_form_opener_reveals_form_never_submits():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<button id='o' onclick=\"window.__o=true\">Apply for this job</button>"
                "<button id='s' onclick=\"window.__s=true\">Apply Now</button>"
                "</body></html>"
            )
            assert await nav.click_form_opener(page) is True
            assert await page.evaluate("window.__o") is True
            assert await page.evaluate("window.__s !== true") is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_wait_for_content_true_when_button_appears():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content("<html><body><p>yukleniyor</p></body></html>")
            await page.evaluate(
                "setTimeout(() => { const b = document.createElement('button');"
                " b.textContent = 'Apply for this job'; document.body.append(b); }, 300)"
            )
            assert await nav.wait_for_content(page, timeout_ms=5000) is True
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_wait_for_content_false_on_timeout():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content("<html><body><p>dugme yok</p></body></html>")
            assert await nav.wait_for_content(page, timeout_ms=500) is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_click_form_opener_returns_false_without_opener():
    from playwright.async_api import async_playwright

    nav = _load("navigation")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<button id='s' onclick=\"window.__s=true\">Submit application</button>"
                "</body></html>"
            )
            assert await nav.click_form_opener(page) is False
            assert await page.evaluate("window.__s !== true") is True
        finally:
            await browser.close()
