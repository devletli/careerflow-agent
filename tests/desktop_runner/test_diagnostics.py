"""Faz 1: kosu raporu + iz teshisi (PII sizintisi yok, 14 gun saklama)."""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"


def _load():
    for module_name in ("desktop_runner", "desktop_runner.diagnostics"):
        sys.modules.pop(module_name, None)
    sys.path.insert(0, str(PACKAGE_DIR.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "desktop_runner.diagnostics", PACKAGE_DIR / "diagnostics.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["desktop_runner.diagnostics"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(PACKAGE_DIR.parent))
        except ValueError:
            pass


EMAIL = "ada.ornekmail@example.com"
PHONE = "+49 170 999888777"


class _Tracing:
    def __init__(self):
        self.start_kwargs = None
        self.stop_path = None

    async def start(self, **kwargs):
        self.start_kwargs = kwargs

    async def stop(self, path=None):
        self.stop_path = path
        Path(path).write_bytes(b"fake-trace")


class _Ctx:
    def __init__(self):
        self.tracing = _Tracing()


def test_report_contains_no_profile_pii(tmp_path):
    diag = _load()
    report = diag.new_report(ats="generic", host="boards.greenhouse.io")
    diag.record_field(report, "email", "filled")
    diag.record_field(report, "phone", "unverified", reason="requires_human")
    diag.record_step(report, "run_assisted", ok=True)
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    diag.write_report(run_dir, {**report, "run_id": "run1"})
    text = (run_dir / "report.json").read_text(encoding="utf-8")
    assert EMAIL not in text
    assert PHONE not in text
    body = json.loads(text)
    assert body["host"] == "boards.greenhouse.io"
    assert body["fields"] == [
        {"key": "email", "outcome": "filled"},
        {"key": "phone", "outcome": "unverified", "reason": "requires_human"},
    ]


def test_write_report_strips_value_keys(tmp_path):
    diag = _load()
    run_dir = tmp_path / "run2"
    run_dir.mkdir()
    diag.write_report(run_dir, {
        "run_id": "run2",
        "ats": "generic",
        "host": "example.com",
        "steps": [],
        # Kotu cagri deger sizdirmaya calissa bile allowlist temizler.
        "fields": [
            {"key": "email", "outcome": "filled", "value": EMAIL,
             "values": [PHONE], "email": EMAIL},
        ],
        "handoffs": 0,
        "timed_out": None,
        "value": EMAIL,
    })
    text = (run_dir / "report.json").read_text(encoding="utf-8")
    assert EMAIL not in text
    assert PHONE not in text
    assert "value" not in json.loads(text)["fields"][0]


@pytest.mark.asyncio
async def test_start_finish_creates_trace_and_report(tmp_path):
    diag = _load()
    ctx = _Ctx()
    run_dir = await diag.start_run(ctx, root=tmp_path)
    assert run_dir.parent == tmp_path
    assert ctx.tracing.start_kwargs == {
        "screenshots": True, "snapshots": True, "sources": False,
    }
    report = diag.new_report(ats="generic", host="example.com")
    diag.record_field(report, "first_name", "filled")
    await diag.finish_run(ctx, run_dir, report, root=tmp_path)
    assert (run_dir / "trace.zip").is_file()
    body = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert body["run_id"] == run_dir.name
    assert body["fields"] == [{"key": "first_name", "outcome": "filled"}]
    assert EMAIL not in (run_dir / "report.json").read_text(encoding="utf-8")


def test_prune_old_runs(tmp_path):
    diag = _load()
    old = tmp_path / "old-run"
    fresh = tmp_path / "fresh-run"
    old.mkdir()
    fresh.mkdir()
    ancient = time.time() - 15 * 86400
    os.utime(old, (ancient, ancient))
    assert diag.prune_old_runs(tmp_path) == 1
    assert not old.exists()
    assert fresh.exists()


def test_runs_root_respects_localappdata(tmp_path, monkeypatch):
    diag = _load()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert diag.runs_root() == tmp_path / "careerflow" / "runs"
