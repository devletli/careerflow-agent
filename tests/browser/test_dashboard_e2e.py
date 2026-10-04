"""Dashboard e2e (live): requires the compose stack on localhost:3000.

Covers yama.md Faz 6: navigation comes from the single TABS array, the
active tab is derived from the URL hash, and tables render on desktop,
tablet, and mobile viewports. Deselected in CI (pytest -m "not live").
"""
import socket

import pytest

pytestmark = pytest.mark.live
pytest.importorskip("playwright")

BASE_URL = "http://localhost:3000"

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 900},
    "tablet": {"width": 1024, "height": 768},
    "mobile": {"width": 390, "height": 844},
}

TABS = ["Overview", "Jobs", "Documents", "Applications", "Events", "Settings"]


def _stack_up():
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", 3000))
        return True
    except OSError:
        return False
    finally:
        s.close()


@pytest.fixture(params=sorted(VIEWPORTS))
def viewport(request):
    return request.param


def _page(pw, viewport):
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport=VIEWPORTS[viewport])
    return browser, page


def test_tabs_come_from_single_array_and_switch(viewport):
    from playwright.sync_api import expect, sync_playwright

    if not _stack_up():
        pytest.skip("dashboard stack not running on localhost:3000")
    with sync_playwright() as pw:
        browser, page = _page(pw, viewport)
        try:
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(BASE_URL + "/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2500)
            labels = page.locator(".tabs .tab").all_inner_texts()
            assert [t.strip() for t in labels] == TABS
            for tab in TABS:
                expect(page.get_by_role("tab", name=tab, exact=True)).to_be_visible()
            for tab in ("Jobs", "Applications", "Documents"):
                page.get_by_role("tab", name=tab, exact=True).click()
                page.wait_for_timeout(1500)
                assert f"#{tab.lower()}" in page.url
                assert (
                    page.locator(".tab-body table.responsive, .tab-body .panel")
                    .first.is_visible()
                )
            assert not errors, errors
        finally:
            browser.close()


def test_deep_link_hash_selects_tab(viewport):
    from playwright.sync_api import sync_playwright

    if not _stack_up():
        pytest.skip("dashboard stack not running on localhost:3000")
    with sync_playwright() as pw:
        browser, page = _page(pw, viewport)
        try:
            page.goto(BASE_URL + "/#documents", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2500)
            active = page.locator(".tabs .tab.active").inner_text().strip()
            assert active == "Documents"
        finally:
            browser.close()
