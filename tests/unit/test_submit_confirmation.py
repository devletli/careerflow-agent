"""yama.md P0 regression tests: click vs confirmation separation.

Offline unit tests with fake pages (no real browser):
- a successful click stays clicked=True even if the confirmation wait times
  out (the reported bug converted it to clicked=False);
- missing submit button reports SUBMIT_BUTTON_NOT_FOUND;
- explicit confirmation text is detected (generic "success" alone is not);
- adapter-specific verify_submission is preferred when present;
- the SUBMITTED / REQUIRES_HUMAN / FILLED outcome rule is pinned.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("playwright")

ROOT = Path(__file__).resolve().parents[2]


def _load_engine():
    path = ROOT / "services" / "browser-agent" / "app" / "engine.py"
    spec = importlib.util.spec_from_file_location("careerflow_engine_confirm", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_engine_confirm"] = module
    spec.loader.exec_module(module)
    return module


_engine = _load_engine()


class _TextNode:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _Button:
    def __init__(self, fail_click=False):
        self.clicked = False
        self._fail_click = fail_click

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self):
        if self._fail_click:
            raise RuntimeError("click exploded")
        self.clicked = True


class _Page:
    """Minimal fake playwright page honouring only what the engine uses."""

    def __init__(self, button=None, confirmation_text=None, wait_timeout_exc=None):
        self.url = "https://example.com/apply"
        self._button = button
        self._confirmation_text = confirmation_text
        self._wait_timeout_exc = wait_timeout_exc

    async def query_selector(self, selector):
        if "text=~" in selector:
            # Emulate selector matching like a real engine would: only
            # explicit confirmation markers match, generic "success" does not.
            if self._confirmation_text is None:
                return None
            haystack = self._confirmation_text.lower()
            markers = (
                "application received",
                "thank you for applying",
                "submission confirmed",
                "your application has been submitted",
                "application submitted",
            )
            if any(marker in haystack for marker in markers):
                return _TextNode(self._confirmation_text)
            return None
        return self._button

    async def wait_for_timeout(self, ms):
        if self._wait_timeout_exc is not None:
            raise self._wait_timeout_exc
        return None


def _run(coro):
    return asyncio.run(coro)


def test_successful_click_survives_confirmation_timeout():
    engine = _engine.BrowserAutomationEngine()
    page = _Page(button=_Button(), wait_timeout_exc=TimeoutError("poll timed out"))
    result = _run(engine._click_submit(page))
    assert result["clicked"] is True
    assert result["confirmed"] is False


def test_missing_button_reports_not_found():
    engine = _engine.BrowserAutomationEngine()
    result = _run(engine._click_submit(_Page(button=None)))
    assert result == {
        "clicked": False,
        "confirmed": False,
        "error": "SUBMIT_BUTTON_NOT_FOUND",
    }


def test_click_failure_reports_clicked_false():
    engine = _engine.BrowserAutomationEngine()
    result = _run(engine._click_submit(_Page(button=_Button(fail_click=True))))
    assert result["clicked"] is False
    assert result["confirmed"] is False


def test_explicit_confirmation_detected():
    engine = _engine.BrowserAutomationEngine()
    page = _Page(
        button=_Button(),
        confirmation_text="Your application has been submitted. Reference 123.",
    )
    result = _run(engine._click_submit(page))
    assert result == {"clicked": True, "confirmed": True, "confirmation": result["confirmation"]}


def test_generic_success_text_is_not_confirmation():
    engine = _engine.BrowserAutomationEngine()
    page = _Page(button=_Button(), confirmation_text="success!")
    result = _run(engine._click_submit(page))
    assert result["clicked"] is True
    assert result["confirmed"] is False


def test_adapter_verification_preferred():
    engine = _engine.BrowserAutomationEngine()
    adapter = AsyncMock()
    adapter.name = "workable-test"
    adapter.verify_submission = AsyncMock(return_value=True)
    page = _Page(button=_Button())
    confirmation = _run(engine._wait_for_confirmation(page, adapter=adapter))
    assert confirmation == {"adapter": "workable-test"}
    adapter.verify_submission.assert_awaited_once()


def test_submission_outcome_rule():
    outcome = _engine.resolve_submission_outcome
    assert outcome(True, True) == "SUBMITTED"
    assert outcome(True, False) == "REQUIRES_HUMAN"
    assert outcome(False, False) == "FILLED"
    assert outcome(False, True) == "FILLED"


def test_fill_result_carries_confirmation_flag():
    from browser.site_adapters.base import FillResult

    assert FillResult().confirmation_detected is False
