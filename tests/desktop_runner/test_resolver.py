"""Faz 4: cozucu + dogrulamali doldurma + hassas-alan korumasi."""

import functools
import http.server
import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

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


FORM = """
<html><body>
  <label for="email">Email</label>
  <input type="email" id="email" name="email">
  <label for="p1">Phone</label>
  <input type="tel" id="p1" aria-label="Phone">
  <label for="p2">Phone</label>
  <input type="tel" id="p2" aria-label="Phone">
  <label for="sal">Salary expectation (annual gross, EUR)</label>
  <input type="text" id="sal" name="salary_expectation">
  <label for="rw">Nickname</label>
  <input type="text" id="rw" name="nickname">
  <label for="inv">Anything</label>
  <input type="text" id="inv" name="anything" aria-invalid="true">
  <input type="password" id="pw" name="password">
</body></html>
"""

COMBO = """
<html><body>
  <label for="country">Country</label>
  <input id="country" role="combobox" aria-expanded="false" aria-label="Country" placeholder="Select...">
  <ul role="listbox" id="lb" hidden>
    <li role="option">Germany</li>
    <li role="option">France</li>
  </ul>
<script>
const inp = document.getElementById('country'), lb = document.getElementById('lb');
inp.addEventListener('input', () => {
  lb.hidden = false;
  const q = inp.value.toLowerCase();
  for (const li of lb.querySelectorAll('[role=option]'))
    li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';
});
lb.addEventListener('click', (e) => {
  if (e.target.getAttribute('role') === 'option') { inp.value = e.target.textContent; lb.hidden = true; }
});
</script>
</body></html>
"""


@pytest.mark.asyncio
async def test_resolve_single_label_and_selector():
    from playwright.async_api import async_playwright

    resolver = _load("resolver")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            found = await resolver.resolve(page, "email")
            assert await found.get_attribute("id") == "email"
            spec = SimpleNamespace(selectors=("#email",), labels=(), kind="text")
            found = await resolver.resolve(page, "email", spec)
            assert await found.get_attribute("id") == "email"
            assert await resolver.resolve(page, "nonexistent_key") is None
            assert await resolver.absence_reason(page, "nonexistent_key") == "not_found"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_resolve_ambiguous_never_guesses():
    from playwright.async_api import async_playwright

    resolver = _load("resolver")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            assert await resolver.resolve(page, "phone") is None
            assert await resolver.absence_reason(page, "phone") == "ambiguous"
            assert await page.locator("#p1").input_value() == ""
            assert await page.locator("#p2").input_value() == ""
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_fill_and_verify_ok_and_rewrite_and_invalid():
    from playwright.async_api import async_playwright

    resolver = _load("resolver")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            assert await resolver.fill_and_verify(
                page.locator("#email"), "a@b.de", 1) == "filled"
            # React-benzeri: alan degeri geri yazar.
            await page.evaluate(
                "document.getElementById('rw').addEventListener('input',"
                " (e) => { e.target.value = 'locked'; })")
            assert await resolver.fill_and_verify(
                page.locator("#rw"), "Ada", 1) == "failed_verify"
            color = await page.locator("#rw").evaluate("(el) => el.style.outlineColor")
            assert "239, 68, 68" in color
            assert await resolver.diagnose(page.locator("#rw"), "Ada") == "value_mismatch"
            # aria-invalid=true dogrulanamadi sayilir.
            assert await resolver.fill_and_verify(
                page.locator("#inv"), "x", 1) == "failed_verify"
            assert await resolver.diagnose(page.locator("#inv"), "x") == "aria_invalid"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_credential_answer_keys_never_resolve():
    from playwright.async_api import async_playwright

    resolver = _load("resolver")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(FORM)
            assert await resolver.resolve(page, "password") is None
            assert await resolver.resolve(page, "one-time-code") is None
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_combobox_exact_match_or_untouched():
    from playwright.async_api import async_playwright

    resolver = _load("resolver")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(COMBO)
            assert await resolver.fill_combobox(
                page.locator("#country"), "Germany") == "filled"
            assert await page.locator("#country").input_value() == "Germany"
            await page.set_content(COMBO)
            assert await resolver.fill_combobox(
                page.locator("#country"), "Atlantis") == "skipped_unverified"
            assert await page.locator("#country").input_value() == ""
            color = await page.locator("#country").evaluate("(el) => el.style.outlineColor")
            assert "234, 179, 8" in color
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_hidden_file_input_attached(tmp_path):
    from playwright.async_api import async_playwright

    documents = _load("documents")
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 fixture")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(
                "<html><body>"
                "<input type='file' id='resume' name='resume' style='display:none'>"
                "</body></html>")
            attached = await documents.attach_files(page, {"resume": cv})
            assert attached == ["resume"]
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_sensitive_never_autofilled_even_when_verified(form_server):
    from playwright.async_api import async_playwright

    assisted = _load("assisted")
    profile = {"name": "Ada Lovelace", "email": "ada@example.com",
               "phone": "", "website": ""}
    verified = {"salary_expectation": "80000", "work_authorization": "yes"}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page, summary = await assisted.run_assisted(
                ctx, f"{form_server}/custom_questions.html",
                profile, verified, _settings(), {},
            )
            assert await page.locator("#salary_expectation").input_value() == ""
            sensitive = [f for f in summary.fields
                         if f.get("outcome") == "skipped_sensitive"]
            keys = " ".join(f.get("key", "") for f in sensitive)
            assert "salary" in keys and "authoriz" in keys
            assert all(f.get("reason") == "sensitive_never_fill"
                       for f in sensitive)
            assert await page.locator("#first_name").input_value() == "Ada"
            assert await page.evaluate("window.__submitted") is False
        finally:
            await browser.close()
