"""Fill-behavior regression tests on ATS-like fixtures.

- Verified fields fill; unverified fields (e.g. work authorization without a
  verified answer) land in skipped_unverified and are never guessed.
- In PREPARE_APPLICATION mode the submit button is never clicked.
"""
from unittest.mock import AsyncMock

import pytest

from browser.site_adapters.base import FieldPlan


def _plan(*fields):
    return list(fields)


@pytest.mark.asyncio
async def test_greenhouse_verified_fill_and_unverified_skip(engine, form_server):
    from playwright.async_api import async_playwright

    plan = _plan(
        FieldPlan("first_name", "First Name", "Ada", "text"),
        FieldPlan("email", "Email", "ada@example.com", "text"),
        FieldPlan("question_authorized", "Are you authorized to work in Germany?", None, "select"),
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/greenhouse_like.html")
            from browser.site_adapters.generic import GenericAdapter

            result = await GenericAdapter().fill(page, plan)
            assert "first_name" in result.filled
            assert "email" in result.filled
            assert "question_authorized" in result.skipped_unverified
            assert await page.locator("#first_name").input_value() == "Ada"
            assert await page.evaluate("window.__submitted") is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_lever_resume_upload_with_verified_path(engine, form_server, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 fixture")
    plan = _plan(
        FieldPlan("first_name", "First Name", "Ada", "text"),
        FieldPlan("resume", "Resume", str(cv), "file"),
        FieldPlan("salary_expectation", "Salary expectation", None, "text"),
    )
    result = await engine.run(f"{form_server}/lever_like.html", plan=plan)
    assert result.blocked_reason is None
    assert "resume" in result.filled
    assert "salary_expectation" in result.skipped_unverified
    assert result.submitted is False


@pytest.mark.asyncio
async def test_prepare_mode_never_clicks_submit(engine, form_server, monkeypatch):
    submit_spy = AsyncMock(return_value=True)
    monkeypatch.setattr(engine, "_click_submit", submit_spy)
    plan = _plan(FieldPlan("firstname", "First name", "Ada", "text"))
    result = await engine.run(
        f"{form_server}/workable_like.html", plan=plan, submit=True, confirmed=True
    )
    # Live settings are PREPARE_APPLICATION without AUTO_SUBMIT: no submit.
    assert result.submitted is False
    submit_spy.assert_not_called()
