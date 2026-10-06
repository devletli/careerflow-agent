"""Faz 2: ATS URL eslesmesi + sayfa/frame algisi (yerel fixture, ag yok)."""

import pytest

from browser.site_adapters.resolve import ats_from_url, detect_ats, host_of


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://job-boards.greenhouse.io/acme", "greenhouse"),
    ("https://dept.greenhouse.io/x", "greenhouse"),
    ("https://jobs.lever.co/acme/abc", "lever"),
    ("https://apply.workable.com/acme/j/123/", "workable"),
    ("https://acme.workable.com/j/123", "workable"),
    ("https://jobs.ashbyhq.com/acme/1", "ashby"),
    ("https://acme.smartrecruiters.com/j/1", "smartrecruiters"),
    ("https://vertigis.recruitee.com/o/cloud-engineer-x", "recruitee"),
    ("https://acme.personio.de/a/1", "personio"),
    ("https://join.com/companies/x/1", "join"),
    ("https://acme.softgarden.io/a/1", "softgarden"),
    ("https://BOARDS.GREENHOUSE.IO/acme", "greenhouse"),
    ("https://example.com:8443/apply", None),
    ("https://evilgreenhouse.io/acme", None),
    ("https://greenhouse.io.evil.com/acme", None),
    ("https://notlever.co/acme", None),
    ("https://acme.example.com/apply", None),
    ("not a url", None),
    ("", None),
])
def test_ats_from_url_table(url, expected):
    assert ats_from_url(url) == expected


def test_host_of_strips_port_and_case():
    assert host_of("https://Example.COM:8443/a") == "example.com"
    assert host_of("not a url") == ""
    assert host_of("") == ""


class _Frame:
    def __init__(self, url):
        self.url = url


class _Page:
    def __init__(self, url, frames=()):
        self.url = url
        self.frames = list(frames)


@pytest.mark.asyncio
async def test_detect_ats_prefers_page_url():
    page = _Page("https://boards.greenhouse.io/a/1",
                 [_Frame("https://acme.example/apply")])
    assert await detect_ats(page) == "greenhouse"


@pytest.mark.asyncio
async def test_detect_ats_finds_iframe_embedded_form():
    page = _Page("https://karriere.example/stelle/1",
                 [_Frame("https://karriere.example/"),
                  _Frame("https://jobs.lever.co/acme/abc")])
    assert await detect_ats(page) == "lever"


@pytest.mark.asyncio
async def test_detect_ats_generic_without_match():
    assert await detect_ats(_Page("https://acme.example/apply")) == "generic"


@pytest.mark.asyncio
async def test_detect_ats_local_fixture_is_generic(form_server):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/greenhouse_like.html")
            assert await detect_ats(page) == "generic"
        finally:
            await browser.close()
