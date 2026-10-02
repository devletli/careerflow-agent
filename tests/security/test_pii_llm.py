"""T4(b) PII-before-LLM + provider logging tests (offline)."""
import importlib.util
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_matcher():
    path = ROOT / "services" / "job-matching" / "app" / "matcher.py"
    spec = importlib.util.spec_from_file_location("careerflow_job_matcher_pii", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_job_matcher_pii"] = module
    spec.loader.exec_module(module)
    return module


def test_llm_profile_facts_contain_no_pii():
    """Only verified non-PII facts reach the LLM (no phone/address/email)."""
    import inspect

    mod = _load_matcher()
    src = inspect.getsource(mod.JobMatchingEngine.add_llm_explanation)
    for banned in ["phone", "address", "master_cv", "email"]:
        # profile_facts dict must not forward these keys
        assert f'"{banned}"' not in src, f"LLM payload must not contain {banned}"
    assert "experience_years" in src and "skills" in src


def test_llm_client_logs_provider_and_model(caplog):
    import asyncio

    from pydantic import BaseModel

    from shared.llm.client import LLMClient

    class R(BaseModel):
        explanation: str = ""
        risks: list[str] = []

    client = LLMClient(provider="gemini", model="gemini-3.6-flash", api_key="")
    with caplog.at_level(logging.INFO, logger="shared.llm.client"):
        asyncio.run(client.generate_structured("sys", "user", R))
    assert any("provider=gemini" in r.message and "gemini-3.6-flash" in r.message for r in caplog.records)


def test_cv_log_line_is_redacted():
    from shared.infra import pii

    msg = "CV for ada@example.com call +49 170 1111111"
    out = pii.redact(msg)
    assert "ada@example.com" not in out
    assert "+49 170 1111111" not in out
