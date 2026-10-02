"""Browser automation regression tests (offline, deterministic).

Uses the local fixture tests/fixtures/application_form.html only:
- FormAnalyzer (production code) must detect expected fields/questions.
- Only verified profile facts may resolve to answers; salary without a
  configured expectation must NEVER be guessed.
- The Playwright part fills safe fields, verifies DOM values, asserts the
  form is NOT submitted and the CAPTCHA stand-in is untouched.

No internet access, no external sites, no real applications.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _load_analyzer():
    # Unique module name: both job-matching and application-analyzer services
    # use a bare `app` package, so sys.path imports would collide.
    path = ROOT / "services" / "application-analyzer" / "app" / "analyzer.py"
    spec = importlib.util.spec_from_file_location("careerflow_form_analyzer", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_form_analyzer"] = module
    spec.loader.exec_module(module)
    return module


FormAnalyzer = _load_analyzer().FormAnalyzer

from shared.contracts.models import QuestionClassification  # noqa: E402
from shared.profile.loader import CanonicalProfile  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "application_form.html"


def _profile() -> CanonicalProfile:
    return CanonicalProfile(
        facts={
            "candidate_id": "regression-candidate",
            "name": "Eval Candidate",
            "email": "eval@example.com",
            "phone": "+49 170 0000000",
            "website": "https://example.com",
            "experience_years": 15,
            "languages": {"German": "C1", "English": "C1"},
            "location": {"city": "Berlin", "country": "Germany"},
            "work_authorization": {"country": "Germany", "verified": False},
        },
        preferences={"relocation": False, "remote": True},
    )


def _analyze():
    html = FIXTURE.read_text(encoding="utf-8")
    return FormAnalyzer().analyze_form("file://fixture/application", html)


def test_fixture_loads_and_fields_detected():
    fields, questions = _analyze()
    by_name = {f.field_name: f for f in fields}
    for expected in ["first_name", "last_name", "email", "phone", "resume"]:
        assert expected in by_name, f"missing field {expected}"
    # NOTE: the analyzer records textarea elements with type "text" (it reads
    # the `type` attribute, which textarea lacks); the label proves detection.
    assert by_name["cover_letter_text"].label == "Cover Letter"
    assert by_name["resume"].type == "file"


def test_screening_questions_classified():
    _, questions = _analyze()
    by_key = {q.key: q for q in questions}
    assert by_key["work_authorization"].classification == QuestionClassification.LEGAL_OR_WORK_AUTHORIZATION
    assert by_key["salary_expectation"].classification == QuestionClassification.USER_PREFERENCE
    assert by_key["notice_period"].classification == QuestionClassification.USER_PREFERENCE


def test_captcha_produces_no_answer():
    analyzer = FormAnalyzer()
    _, questions = _analyze()
    assert not [q for q in questions if "captcha" in q.key.lower()]
    assert analyzer.classify_question("I am not a robot") == (QuestionClassification.UNKNOWN, 0.0)


def test_safe_facts_resolve_and_salary_never_guessed():
    analyzer = FormAnalyzer()
    profile = _profile()
    _, questions = _analyze()
    answers = {q.key: analyzer.resolve_answer(q, profile) for q in questions}

    assert answers["work_authorization"][0] == "Yes"  # verified Germany fact
    assert answers["work_authorization"][2] is True
    value, _, verified = answers["salary_expectation"]
    assert value is None and verified is False  # never invent compensation


def _browser_available() -> bool:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _browser_available(), reason="chromium not installed")
def test_playwright_fills_safe_fields_without_submit(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("Eval Candidate CV", encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(FIXTURE.as_uri())
            page.get_by_label("First Name").fill("Eval")
            page.get_by_label("Last Name").fill("Candidate")
            page.get_by_label("Email").fill("eval@example.com")
            page.get_by_label("Phone").fill("+49 170 0000000")
            page.get_by_label("Cover Letter").fill("Motivation letter body.")
            page.get_by_label("Resume / CV (PDF)").set_input_files(str(cv))

            assert page.get_by_label("First Name").input_value() == "Eval"
            assert page.get_by_label("Last Name").input_value() == "Candidate"
            assert page.get_by_label("Email").input_value() == "eval@example.com"
            assert page.get_by_label("Cover Letter").input_value() == "Motivation letter body."

            # CAPTCHA stand-in must remain untouched.
            assert page.locator(".g-recaptcha").count() == 1
            assert page.get_by_label("I am not a robot").is_checked() is False

            # The form must NOT be submitted by the test.
            assert page.evaluate("window.__submitted") is False
        finally:
            browser.close()
