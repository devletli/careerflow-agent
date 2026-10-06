"""F5: skor paneli sözleşmesi (statik, offline).

- Overview skoru /api/v1/stats/score-distribution'dan çeker, mini bar çizer.
- QUALIFIED=0 ise panel "En yüksek skor X, eşik Y. REVIEW listesine bak."
  mesajı + REVIEW filtresi; eşik asla değiştirilmez (salt gösterim).
"""
from pathlib import Path

from tests.unit._frontend_src import read_frontend_sources

ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "services" / "frontend" / "app" / "components" / "tabs" / "OverviewTab.js"


def test_stats_route_exists_in_backend():
    from services.api.app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/stats/score-distribution" in paths
    assert "get" in paths["/api/v1/stats/score-distribution"]


def test_overview_renders_distribution_and_empty_panel():
    overview = OVERVIEW.read_text(encoding="utf-8")
    assert "/api/v1/stats/score-distribution" in overview
    assert "STRINGS.scoreDist" in overview
    assert "STRINGS.scoreEmpty" in overview
    assert "STRINGS.reviewList" in overview
    # QUALIFIED=0 senaryosu REVIEW band filtresine gider, eşiği değiştirmez.
    assert '"REVIEW"' in overview or "'REVIEW'" in overview
    src = read_frontend_sources()
    assert "MIN_MATCH_SCORE" not in src, "eşik frontend'den değiştirilemez"


def test_score_messages_translated():
    import json

    for name in ("en.json", "tr.json"):
        d = json.loads((ROOT / "services" / "frontend" / "i18n" / name).read_text(encoding="utf-8"))
        assert "scoreDist" in d and "scoreEmpty" in d and "reviewList" in d
        assert "{max}" in d["scoreEmpty"] and "{threshold}" in d["scoreEmpty"]
