"""PII log-redaction tests (offline, no profile PII committed)."""
import logging

from shared.config import settings
from shared.infra import pii


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, (), None)


def test_email_masked():
    rec = _record("contact ada@example.com for details")
    assert pii.PiiRedactingFilter().filter(rec) is True
    assert "ada@example.com" not in rec.msg
    assert "***" in rec.msg


def test_phone_masked_but_ports_and_counts_untouched():
    rec = _record("call +49 170 1111111, redis at 172.24.0.1:6379, 100 jobs, port 5432")
    pii.PiiRedactingFilter().filter(rec)
    assert "+49 170 1111111" not in rec.msg
    assert "172.24.0.1:6379" in rec.msg
    assert "100 jobs" in rec.msg
    assert "5432" in rec.msg


def test_timestamps_untouched():
    rec = _record("2026-10-02 11:20:13,058 [INFO] job matched")
    pii.PiiRedactingFilter().filter(rec)
    assert "2026-10-02 11:20:13" in rec.msg


def test_candidate_name_masked(tmp_path, monkeypatch):
    profile = tmp_path / "profile.yaml"
    profile.write_text("candidate:\n  name: 'Testperson Unique'\n", encoding="utf-8")
    pii.reset_names_cache()
    try:
        masked = pii.redact("hired Testperson Unique today", str(profile))
        assert "Testperson Unique" not in masked and "***" in masked
    finally:
        pii.reset_names_cache()


def test_redaction_disabled_passes_through(monkeypatch):
    monkeypatch.setattr(settings, "LOG_REDACT_PII", False)
    rec = _record("contact ada@example.com now")
    pii.PiiRedactingFilter().filter(rec)
    assert "ada@example.com" in rec.msg
