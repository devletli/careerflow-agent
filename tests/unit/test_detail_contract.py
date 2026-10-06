"""F6: detay tek-birincil-düğme sözleşmesi (statik, offline).

- Detay üstünde STATUS_UX.next'e göre tek büyük düğme + blokaj nedeni +
  çözüm cümlesi; bilinmeyen durum çökmez (statusUxFor yedeği).
- Belgeler: son sürüm rozeti + aç/indir (API stream); zaman çizelgesi sayfada.
- Submit/onay-token akışına dokunulmaz.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DETAIL = ROOT / "services" / "frontend" / "app" / "applications" / "[id]" / "page.js"


def test_detail_has_single_primary_banner():
    src = DETAIL.read_text(encoding="utf-8")
    assert "statusUxFor" in src and "statusLabel" in src
    assert "PrimaryBanner" in src
    assert "primary-btn" in src
    # Blokaj nedeni + çözüm cümlesi rozetin yanında.
    assert "blocked_reason" in src and "failure_reason" in src
    assert "STRINGS.solutionBlocked" in src
    assert "STRINGS.solutionFailed" in src
    assert "STRINGS.solutionHuman" in src


def test_detail_docs_stream_and_timeline_stay():
    src = DETAIL.read_text(encoding="utf-8")
    assert "doc.view_url" in src and "doc.download_url" in src
    assert "STRINGS.download" in src
    assert 'id="timeline"' in src and 'id="docs"' in src
    assert "STRINGS.timeline" in src


def test_detail_does_not_bypass_submit_guards():
    src = DETAIL.read_text(encoding="utf-8")
    # Birincil düğme yalnızca tokensiz execute aksiyonlarını çağırır.
    assert "/execute" in src
    primary_block = src.split("const runPrimary")[1].split("};")[0]
    assert "confirmation_token" not in primary_block
    assert '"submit"' not in primary_block and "'submit'" not in primary_block
    # Mevcut pipeline submit akışı (token korumalı) aynen durur.
    assert "submit_application" in src


def test_detail_messages_translated():
    import json

    for name in ("en.json", "tr.json"):
        d = json.loads((ROOT / "services" / "frontend" / "i18n" / name).read_text(encoding="utf-8"))
        for key in ("primaryReview", "solutionBlocked", "solutionFailed", "solutionHuman"):
            assert key in d, f"{name}: {key} yok"
