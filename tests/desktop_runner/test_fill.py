"""Fill rules: visible typing, never overwrite, never touch credentials."""

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


FORM = """
<html><body>
  <input type="text" id="empty" name="first_name">
  <input type="text" id="pre" name="last_name" value="Kaya">
  <input type="password" id="pw" name="password">
  <input type="text" id="otp" name="code" autocomplete="one-time-code">
  <select id="sel" name="city"><option value="">Sec</option><option>Berlin</option></select>
  <select id="sel2" name="country"><option value="">Sec</option><option selected>Almanya</option></select>
  <input type="checkbox" id="cb" name="agree">
  <input type="checkbox" id="cb2" name="news" checked>
  <input type="text" id="todo" name="notes">
</body></html>
"""


@pytest.mark.asyncio
async def test_fill_field_types_visibly_and_marks_green():
    from playwright.async_api import async_playwright

    fill = _load("fill")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            status = await fill.fill_field(page.locator("#empty"), "Ada", 1)
            assert status == "filled"
            assert await page.locator("#empty").input_value() == "Ada"
            color = await page.locator("#empty").evaluate("(el) => el.style.outlineColor")
            width = await page.locator("#empty").evaluate("(el) => el.style.outlineWidth")
            assert "34, 197, 94" in color
            assert width == "3px"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_prefilled_value_never_overwritten():
    from playwright.async_api import async_playwright

    fill = _load("fill")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            assert await fill.fill_field(page.locator("#pre"), "Ada", 1) == "skipped_prefilled"
            assert await page.locator("#pre").input_value() == "Kaya"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_password_raises_and_otp_skipped():
    from playwright.async_api import async_playwright

    fill = _load("fill")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            with pytest.raises(RuntimeError):
                await fill.fill_field(page.locator("#pw"), "s3cret", 1)
            assert await page.locator("#pw").input_value() == ""
            assert await fill.fill_field(page.locator("#otp"), "123456", 1) == "skipped_credential"
            assert await page.locator("#otp").input_value() == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_select_and_checkbox_skip_when_set():
    from playwright.async_api import async_playwright

    fill = _load("fill")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            assert await fill.set_select(page.locator("#sel"), "Berlin") == "filled"
            assert await fill.set_select(page.locator("#sel2"), "Berlin") == "skipped_prefilled"
            assert await fill.set_checkable(page.locator("#cb"), True) == "filled"
            assert await page.locator("#cb").is_checked() is True
            assert await fill.set_checkable(page.locator("#cb2"), True) == "skipped_prefilled"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_mark_unverified_outlines_yellow():
    from playwright.async_api import async_playwright

    fill = _load("fill")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            await fill.mark_unverified(page, [page.locator("#todo")])
            color = await page.locator("#todo").evaluate("(el) => el.style.outlineColor")
            assert "234, 179, 8" in color
            assert await page.locator("#todo").input_value() == ""
        finally:
            await browser.close()
