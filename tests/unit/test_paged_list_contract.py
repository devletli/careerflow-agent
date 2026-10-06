"""Ortak sayfalama kancası sözleşmesi (statik, offline).

- fetchPage useRef içinde tutulur (bağımlılık dizisinde DEĞİL; sonsuz
  istek döngüsü yok), polling kancanın içindedir (cursor sabit,
  visibilityState kontrolü, hata olunca son veri korunur).
- Filtre değişince reset için ayrı efekt YOK; {key, stack} state'i kullanılır.
- Toplu seçim id kümesi üst bileşendedir (polling'den sonra korunur).
- Sayfa 2'ye geçince polling cursor'ı sıfırlamaz (cursor stack'te durur).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "services" / "frontend" / "app" / "hooks" / "usePagedList.js"
PAGE = ROOT / "services" / "frontend" / "app" / "page.js"


def test_hook_keeps_fetch_in_ref_and_polls_inside():
    src = HOOK.read_text(encoding="utf-8")
    assert "fetchRef" in src and "useRef" in src
    assert "visibilityState" in src
    # Hata olunca son veri korunur: catch bloğu setData çağırmaz.
    catch_block = src.split("catch")[1][:200]
    assert "setError" in catch_block and "setData" not in catch_block
    # Ayrı reset efekti yok; {key, stack} kullanılır.
    assert "stack" in src and "key" in src
    assert "setStack([null])" not in src


def test_lists_use_shared_hook_with_stable_cursor():
    src = PAGE.read_text(encoding="utf-8")
    assert src.count("usePagedList") >= 3, "applications + documents ortak kancayı kullanmalı"
    assert "next_cursor" in src
    # Seçim üst bileşende; tablo yalnızca okur.
    assert "jobs.selected" in src


def test_followup_unwraps_paged_envelope():
    """Regresyon: /applications zarf ({items,...}) döndürür; FollowUpPanel
    diziyi spread etmeden önce items'a çözer, yoksa istemci çöker."""
    overview = (ROOT / "services" / "frontend" / "app" / "components" / "tabs" / "OverviewTab.js").read_text(
        encoding="utf-8"
    )
    assert ".items" in overview, "sayfalı zarf çözülmeli"
    assert "Array.isArray" in overview
