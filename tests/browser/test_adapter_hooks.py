"""Faz 3: adapter kancalari (form_root / field_specs / pre_fill).

- Kayitli her adapter kancalari sunar, submit yetenegi yoktur.
- Seciciler gercek sayfalardan kaydedilmistir (adapter docstring'inde
  kaynak); workable'da uydurma secici yoktur.
- Hicbir spec hassas kategoriye (izin/maas/demografik/saglik) dokunmaz.
- pre_fill yalnizca reject tiklar, accept-all'e asla dokunmaz.
"""
import pytest

from browser.site_adapters.ashby import AshbyAdapter
from browser.site_adapters.greenhouse import GreenhouseAdapter
from browser.site_adapters.lever import LeverAdapter
from browser.site_adapters.registry import resolve
from browser.site_adapters.workable import WorkableAdapter

ALL = (GreenhouseAdapter(), LeverAdapter(), AshbyAdapter(), WorkableAdapter())

SENSITIVE_RX_SRC = ("authoriz", "salary", "citizen", "nationality", "race",
                    "gender", "disab", "health", "eeo", "religion")


def test_all_adapters_expose_hooks_and_no_submit():
    for adapter in ALL:
        assert not hasattr(adapter, "submit")
        assert callable(adapter.fill)
        assert callable(adapter.detect_blockers)
        assert callable(adapter.form_root)
        assert callable(adapter.field_specs)
        assert callable(adapter.pre_fill)
        assert isinstance(adapter.field_specs(), dict)


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://job-boards.greenhouse.io/acme", "greenhouse"),
    ("https://jobs.lever.co/acme/abc", "lever"),
    ("https://myorg.workable.com/j/123", "workable"),
    ("https://jobs.ashbyhq.com/acme/1", "ashby"),
    ("https://evilgreenhouse.io/acme", "generic"),
    ("https://greenhouse.io.evil.com/acme", "generic"),
    ("https://notlever.co/acme", "generic"),
    ("https://example.com/apply", "generic"),
])
def test_registry_routes_by_exact_ats(url, expected):
    assert resolve(url).name == expected


def test_recorded_specs_have_selectors_workable_has_none():
    gh = GreenhouseAdapter().field_specs()
    assert gh["first_name"].selectors and gh["email"].selectors
    assert gh["resume"].selectors and gh["resume"].kind == "file"
    assert gh["location"].kind == "combobox"
    lv = LeverAdapter().field_specs()
    assert lv["full_name"].selectors and lv["resume"].selectors
    assert lv["resume"].kind == "file"
    ab = AshbyAdapter().field_specs()
    assert ab["email"].selectors and ab["resume"].selectors
    assert ab["phone"].selectors == ()  # kararli secici yok: etiketle
    wb = WorkableAdapter().field_specs()
    assert wb, "workable en az etiketleri sunar"
    assert all(not spec.selectors for spec in wb.values()), \
        "kayit yokken uydurma secici yasak"


def test_no_spec_touches_sensitive_categories():
    offenders = []
    for adapter in ALL:
        for key, spec in adapter.field_specs().items():
            hay = " ".join([key, *spec.labels]).lower()
            if any(s in hay for s in SENSITIVE_RX_SRC):
                offenders.append(f"{adapter.name}:{key}")
    assert offenders == []


def test_field_spec_kinds_are_valid():
    for adapter in ALL:
        for key, spec in adapter.field_specs().items():
            assert spec.kind in ("text", "select", "combobox", "file", "checkbox"), \
                f"{adapter.name}:{key}"


@pytest.mark.asyncio
async def test_form_root_scopes_to_application_form(form_server):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/greenhouse_like.html")
            root = await GreenhouseAdapter().form_root(page)
            assert await root.locator("#first_name").count() == 1
            await page.goto(f"{form_server}/lever_like.html")
            root = await LeverAdapter().form_root(page)
            assert await root.locator("#name").count() == 1
            await page.goto(f"{form_server}/posting_no_form.html")
            assert await AshbyAdapter().form_root(page) == page
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_pre_fill_clicks_only_reject(form_server):
    from playwright.async_api import async_playwright

    from browser.site_adapters.generic import GenericAdapter

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/cookie_banner.html")
            await GenericAdapter().pre_fill(page)
            assert await page.evaluate("window.__rejected") is True
            assert await page.evaluate("window.__accepted") is False

            await page.goto(f"{form_server}/lever_cc_banner.html")
            await GenericAdapter().pre_fill(page)
            assert await page.evaluate("window.__rejected") is False
            await LeverAdapter().pre_fill(page)
            assert await page.evaluate("window.__rejected") is True
            assert await page.evaluate("window.__accepted") is False
        finally:
            await browser.close()
