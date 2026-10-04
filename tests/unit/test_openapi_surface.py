"""A4: openapi yuzey snapshot (router bolunmesi sonrasi guvence).

Yuzey degisikligi (route ekleme/kaldirma) bu testi kirmizi yapar;
bilincli degisiklikte snapshot UPDATE_SNAPSHOT=1 ile yenilenir ve
fark rapora yazilir.
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))

from services.api.app.main import app  # noqa: E402

SNAP = ROOT / "tests" / "snapshots" / "openapi_surface.json"


def current_surface() -> list:
    return sorted(
        [p, m.upper()]
        for p, v in app.openapi()["paths"].items()
        for m in v
        if m in {"get", "post", "patch", "put", "delete"}
    )


def test_openapi_surface_unchanged():
    cur = current_surface()
    if os.environ.get("UPDATE_SNAPSHOT") == "1":
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    assert SNAP.exists(), "snapshot yok: UPDATE_SNAPSHOT=1 ile bir kez uret"
    assert cur == json.loads(SNAP.read_text(encoding="utf-8")), "API route yuzeyi degisti"
