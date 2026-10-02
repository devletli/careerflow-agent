"""T6 Greenhouse + Lever submission-adapter tests (PREPARE-only).

Local fixtures only (form_server); no internet, no real sites, no real
applications. New adapter = one file + registry entry + fixture + test;
core (engine/generic) untouched.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from browser.site_adapters.base import FieldPlan
from browser.site_adapters.greenhouse import GreenhouseAdapter
from browser.site_adapters.lever import LeverAdapter
from browser.site_adapters.registry import resolve

ROOT = Path(__file__).resolve().parents[2]


def _load_analyzer():
    path = ROOT / "services" / "application-analyzer" / "app" / "analyzer.py"
    spec = importlib.util.spec_from_file_location("careerflow_form_analyzer_t6", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_form_analyzer_t6"] = module
    spec.loader.exec_module(module)
    return module.FormAnalyzer()


def test_resolve_prefers_greenhouse_and_lever():
    assert resolve("https://boards.greenhouse.io/fixturecorp/jobs/123").name == "greenhouse"
    assert resolve("https://job-boards.greenhouse.io/fixturecorp").name == "greenhouse"
    assert resolve("https://jobs.lever.co/fixturecorp/abc").name == "lever"
    # generic fallback untouched
    assert resolve("https://example.com/apply").name == "generic"
    assert resolve("https://myorg.workable.com/j/123").name == "workable"


def test_adapters_expose_no_submit_capability():
    for adapter in (GreenhouseAdapter(), LeverAdapter()):
        assert not hasattr(adapter, "submit")
        assert callable(adapter.fill)
        assert callable(adapter.detect_blockers)


@pytest.mark.asyncio
async def test_greenhouse_fills_verified_and_skips_unverified(form_server, tmp_path):
    from playwright.async_api import async_playwright

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture")
    cover = tmp_path / "cover.pdf"
    cover.write_bytes(b"%PDF-1.4 fixture")
    plan = [
        FieldPlan("first_name", "First Name", "Ada", "text"),
        FieldPlan("last_name", "Last Name", "Lovelace", "text"),
        FieldPlan("email", "Email", "ada@example.com", "text"),
        FieldPlan("phone", "Phone", "+49 170 1111111", "text"),
        FieldPlan("linkedin", "LinkedIn Profile", "https://linkedin.com/in/ada", "text"),
        FieldPlan("resume", "Resume / CV", str(resume), "file"),
        FieldPlan("cover_letter", "Cover Letter", str(cover), "file"),
        FieldPlan("question_years", "How many years of DevOps experience?", "8", "text"),
        # No verified answer: work authorization must never be guessed.
        FieldPlan("question_authorized", "Are you authorized to work in Germany?", None, "select"),
    ]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(f"{form_server}/greenhouse_like.html")
            result = await GreenhouseAdapter().fill(page, plan)
            for key in ("first_name", "last_name", "email", "phone", "linkedin",
                        "resume", "cover_letter", "question_years"):
                assert key in result.filled, f"{key} should be filled"
            assert "question_authorized" in result.skipped_unverified
            assert await page.locator("#first_name").input_value() == "Ada"
            assert await page.locator("#last_name").input_value() == "Lovelace"
            assert await page.locator("#email").input_value() == "ada@example.com"
            assert await page.locator("#linkedin").input_value() == "https://linkedin.com/in/ada"
            assert await page.evaluate("window.__submitted") is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_lever_fills_verified_and_skips_unverified(form_server, tmp_path, engine):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture")
    plan = [
        FieldPlan("email", "Email", "ada@example.com", "text"),
        FieldPlan("phone", "Phone", "+49 170 1111111", "text"),
        FieldPlan("linkedin", "LinkedIn profile URL", "https://linkedin.com/in/ada", "text"),
        FieldPlan("comments", "Additional information / cover letter", "Verified cover letter text.", "text"),
        FieldPlan("resume", "Resume", str(resume), "file"),
        # No verified answers: EEO + salary must never be guessed.
        FieldPlan("eeo_work_auth", "Are you legally authorized to work in Germany?", None, "select"),
        FieldPlan("salary_expectation", "Salary expectation", None, "text"),
    ]
    result = await engine.run(f"{form_server}/lever_like.html", plan=plan)
    assert result.blocked_reason is None
    for key in ("email", "phone", "linkedin", "comments", "resume"):
        assert key in result.filled, f"{key} should be filled"
    assert "eeo_work_auth" in result.skipped_unverified
    assert "salary_expectation" in result.skipped_unverified
    assert result.submitted is False


@pytest.mark.asyncio
async def test_prepare_mode_never_submits_greenhouse_or_lever(engine, form_server):
    plan = [FieldPlan("first_name", "First Name", "Ada", "text")]
    for page_name in ("greenhouse_like.html", "lever_like.html"):
        result = await engine.run(
            f"{form_server}/{page_name}", plan=plan, submit=True, confirmed=True
        )
        # Settings are PREPARE_APPLICATION without AUTO_SUBMIT: fill-only.
        assert result.submitted is False


def test_fixture_questions_map_to_form_analysis_classes():
    analyzer = _load_analyzer()
    cases = {
        "Are you authorized to work in Germany?": "LEGAL_OR_WORK_AUTHORIZATION",
        "Are you legally authorized to work in Germany?": "LEGAL_OR_WORK_AUTHORIZATION",
        "Salary expectation (annual gross, EUR)": "USER_PREFERENCE",
        "How many years of DevOps experience do you have?": "SAFE_TRANSFORMATION",
        "LinkedIn Profile": "SAFE_FACT",
    }
    for text, expected in cases.items():
        classification, _ = analyzer.classify_question(text)
        assert classification.value == expected, f"{text!r} -> {classification}"
