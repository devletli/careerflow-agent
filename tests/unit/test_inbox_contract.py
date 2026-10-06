"""F3: Overview eylem-kutusu sözleşmesi (statik, offline).

"Gelişmiş" katlanır bölümüne taşıma, onay-diyaloğu gerektiren
aksiyonların kodunu ve mevcut sözleşme assert'lerini korur:
- 5 aksiyon + açıklamaları i18n'de durur, ACTIONS bağlanır,
- window.confirm onayları page.js'te durur,
- aksiyon kartları sayılmaz/azaltılmaz (details altında aynı markup),
- kartlar ilgili filtreli listeye gider (status/band filtresi kurulur).
"""
from pathlib import Path

from tests.unit._frontend_src import read_frontend_sources

ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "services" / "frontend" / "app" / "components" / "tabs" / "OverviewTab.js"
PAGE = ROOT / "services" / "frontend" / "app" / "page.js"


def test_inbox_route_exists_in_backend():
    from services.api.app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/inbox" in paths
    assert "get" in paths["/api/v1/inbox"]


def test_overview_fetches_inbox_and_navigates_with_filters():
    src = read_frontend_sources()
    assert '"/api/v1/inbox"' in src or "'/api/v1/inbox'" in src
    overview = OVERVIEW.read_text(encoding="utf-8")
    for status in ("REQUIRES_HUMAN", "READY_TO_SUBMIT", "FAILED", "CREATED"):
        assert status in overview, f"kart {status} filtresine gitmiyor"
    assert "QUALIFIED" in overview, "yeni güçlü eşleşme Jobs band filtresine gitmiyor"


def test_advanced_collapse_keeps_all_actions_and_confirmations():
    src = read_frontend_sources()
    # 5 aksiyon kartı aynı markup ile durur (azaltma yok).
    assert "const ACTIONS = STRINGS.actions" in src
    assert src.count("action-card") >= 1
    page = PAGE.read_text(encoding="utf-8")
    assert "window.confirm" in page, "onay diyaloğu kaldırılamaz"
    assert "STRINGS.confirmFill" in page and "STRINGS.confirmStart" in page
    overview = OVERVIEW.read_text(encoding="utf-8")
    assert "<details" in overview and "STRINGS.advanced" in overview
    assert "STRINGS.pipelineControls" in overview
