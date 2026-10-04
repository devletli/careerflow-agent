"""Faz 1C: LLM model acilis dogrulamasi (sahte istemci, ag yok) + Faz 1E bayraklari."""
from types import SimpleNamespace

from shared.config import settings
from shared.llm.models import llm_status, resolve_model, validate_llm_at_startup


class _FakeModels:
    def __init__(self, names, fail=False):
        self._names = names
        self._fail = fail

    def list(self):
        if self._fail:
            raise RuntimeError("network down")
        return [SimpleNamespace(name=f"models/{n}") for n in self._names]


class _FakeClient:
    def __init__(self, names=("gemini-2.0-flash", "gemini-2.5-flash"), fail=False):
        self.models = _FakeModels(names, fail)


def test_resolve_model_valid():
    assert resolve_model(_FakeClient(), "gemini-2.0-flash") == "gemini-2.0-flash"


def test_resolve_model_invalid_returns_none():
    assert resolve_model(_FakeClient(), "gemini-3.6-flash") is None


def test_resolve_model_list_failure_returns_none():
    assert resolve_model(_FakeClient(fail=True), "gemini-2.0-flash") is None


async def test_validate_disabled_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "LLM_MODEL", "gemini-2.0-flash")
    result = await validate_llm_at_startup()
    assert result["state"] == "disabled"
    assert llm_status()["state"] == "disabled"


async def test_validate_disabled_without_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(settings, "LLM_MODEL", "")
    result = await validate_llm_at_startup()
    assert result["state"] == "disabled"


async def test_validate_non_gemini_provider_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    result = await validate_llm_at_startup()
    assert result["state"] == "disabled"


def test_connector_flags_exist_and_default_true():
    for name in (
        "WORKABLE_ENABLED",
        "GREENHOUSE_ENABLED",
        "LEVER_ENABLED",
        "ASHBY_ENABLED",
        "SMARTRECRUITERS_ENABLED",
        "BUNDESAGENTUR_ENABLED",
        "ARBEITNOW_ENABLED",
    ):
        assert getattr(settings, name, None) is True, f"missing flag {name}"
