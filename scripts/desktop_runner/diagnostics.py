"""Run diagnostics: per-run report.json + Playwright trace.zip (local only).

Her runner kosusu repo DISI bir klasore rapor yazar:
    %LOCALAPPDATA%\\careerflow\\runs\\<run_id>\\   (yoksa ~/.careerflow/runs)

Icerik:
- report.json: ATS adi, host, adimlar, ALAN BASINA sonuc
  (key, outcome, reason; DEGERLER YOK).
- trace.zip: Playwright izi (sayfa icerigi + yazilan degerleri tasir;
  yalnizca yerelde kalir, asla yuklenmez/loglanmaz).

14 gunden eski kosu klasorleri otomatik silinir. Report yazimi allowlist
temellidir: deger tasiyabilecek anahtarlar ("value", "values", e-posta /
telefon iceren serbest metinler) rapora giremez.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

RETENTION_SECONDS = 14 * 86400

# Spec uyumlulugu icin modul sabiti; fonksiyonlar canli runs_root() kullanir
# (boylece testler LOCALAPPDATA'yi monkeypatch'leyebilir).
RUNS = Path(
    os.path.expandvars(r"%LOCALAPPDATA%\careerflow\runs")
    if os.environ.get("LOCALAPPDATA")
    else str(Path.home() / ".careerflow" / "runs")
)


def runs_root() -> Path:
    """Kosu klasorlerinin koku (repo disi)."""
    local = os.environ.get("LOCALAPPDATA")
    if local and local.strip():
        return Path(local) / "careerflow" / "runs"
    return Path.home() / ".careerflow" / "runs"


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def new_report(*, ats: str = "generic", host: str = "") -> dict:
    return {
        "ats": ats,
        "host": host,
        "steps": [],
        "fields": [],
        "handoffs": 0,
        "timed_out": None,
    }


def record_field(report: dict, key: str, outcome: str, reason: str | None = None) -> None:
    """Alan basina sonuc; deger almaz (key/outcome/reason disinda bisey yazilmaz)."""
    entry: dict = {"key": str(key), "outcome": str(outcome)}
    if reason:
        entry["reason"] = str(reason)
    report.setdefault("fields", []).append(entry)


def record_step(report: dict, name: str, ok: bool | None = None,
                reason: str | None = None) -> None:
    entry: dict = {"name": str(name)}
    if ok is not None:
        entry["ok"] = bool(ok)
    if reason:
        entry["reason"] = str(reason)
    report.setdefault("steps", []).append(entry)


def _clean_field(entry: object) -> dict:
    if not isinstance(entry, dict):
        return {"key": str(entry), "outcome": "unknown"}
    clean: dict = {
        "key": str(entry.get("key", "")),
        "outcome": str(entry.get("outcome", "unknown")),
    }
    reason = entry.get("reason")
    if reason:
        clean["reason"] = str(reason)
    return clean


def _clean_step(entry: object) -> dict:
    if not isinstance(entry, dict):
        return {"name": str(entry)}
    clean: dict = {"name": str(entry.get("name", ""))}
    if "ok" in entry:
        clean["ok"] = bool(entry.get("ok"))
    if entry.get("reason"):
        clean["reason"] = str(entry.get("reason"))
    return clean


def sanitized_report(report: dict) -> dict:
    """Raporu allowlist'e indirger; deger tasiyabilecek alanlari atar."""
    return {
        "run_id": str(report.get("run_id", "")),
        "started_at": str(report.get("started_at", "")),
        "ats": str(report.get("ats", "generic")),
        "host": str(report.get("host", "")),
        "steps": [_clean_step(s) for s in report.get("steps", []) or []],
        "fields": [_clean_field(f) for f in report.get("fields", []) or []],
        "handoffs": int(report.get("handoffs", 0) or 0),
        "timed_out": (
            str(report.get("timed_out"))
            if report.get("timed_out") is not None
            else None
        ),
    }


def write_report(run_dir: Path, report: dict) -> Path:
    path = Path(run_dir) / "report.json"
    path.write_text(
        json.dumps(sanitized_report(report), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return path


def prune_old_runs(root: Path | None = None, max_age_s: int = RETENTION_SECONDS) -> int:
    """14 gunden eski kosu klasorlerini siler; silinen sayiyi doner."""
    base = Path(root) if root is not None else runs_root()
    try:
        entries = list(base.iterdir())
    except OSError:
        return 0
    cutoff = time.time() - max_age_s
    pruned = 0
    for entry in entries:
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                pruned += 1
        except OSError:
            continue
    return pruned


def _unique_run_dir(root: Path) -> Path:
    base = time.strftime("%Y%m%d-%H%M%S")
    candidate = root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{base}-{suffix:02d}"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


async def start_run(ctx, *, root: Path | None = None) -> Path:
    """Izlemeyi baslatir, kosu klasorunu doner."""
    base = Path(root) if root is not None else runs_root()
    run_dir = _unique_run_dir(base)
    await ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
    return run_dir


async def finish_run(ctx, run_dir: Path, report: dict,
                     *, root: Path | None = None) -> None:
    """Izi durdurur (trace.zip), report.json yazar, eski kosulari temizler."""
    run_dir = Path(run_dir)
    report = dict(report)
    report.setdefault("run_id", run_dir.name)
    report.setdefault("started_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        await ctx.tracing.stop(path=str(run_dir / "trace.zip"))
    except Exception:
        pass
    write_report(run_dir, report)
    try:
        prune_old_runs(root if root is not None else run_dir.parent)
    except Exception:
        pass
