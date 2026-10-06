"""F4: toplu hazırlık sözleşmesi (statik, offline).

- Jobs çoklu seçim id kümesi üst bileşende tutulur (polling/sayfa sonrası korunur).
- "Hazırla (N)" üst sınırı (20) + onay diyaloğu; ilerleme göstergesi.
- Toplu akış yalnızca /jobs/prepare çağırır; fill/submit komutları girmez,
  onay token'ı gerekmez (tarayıcı aksiyonu değil).
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))
JOBS_TAB = ROOT / "services" / "frontend" / "app" / "components" / "tabs" / "JobsTab.js"
PAGE = ROOT / "services" / "frontend" / "app" / "page.js"


def test_prepare_route_exists_in_backend():
    from services.api.app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/jobs/prepare" in paths
    assert "post" in paths["/api/v1/jobs/prepare"]


def test_selection_lives_above_the_table():
    page = PAGE.read_text(encoding="utf-8")
    assert "jobs.selected" in page, "seçim üst bileşende (kalıcı) tutulmalı"
    assert "selectedJobIds" in page
    tab = JOBS_TAB.read_text(encoding="utf-8")
    assert "selectedIds" in tab and "onToggleSelect" in tab
    assert 'type="checkbox"' in tab


def test_prepare_button_has_cap_confirm_and_progress():
    tab = JOBS_TAB.read_text(encoding="utf-8")
    assert "STRINGS.prepareSelected" in tab
    assert "STRINGS.tooManySelected" in tab
    assert "<progress" in tab
    page = PAGE.read_text(encoding="utf-8")
    assert "STRINGS.confirmPrepare" in page and "window.confirm" in page
    assert "/api/v1/jobs/prepare" in page
    # Toplu akış fill/submit çağırmaz, token istemez.
    prepare_block = page.split("const prepareSelected")[1].split("const archiveJob")[0]
    assert "/api/v1/jobs/prepare" in prepare_block
    assert "pipeline/actions" not in prepare_block
    assert "/execute" not in prepare_block
    assert "confirmation_token" not in prepare_block


def test_prepare_messages_translated():
    import json

    for name in ("en.json", "tr.json"):
        d = json.loads((ROOT / "services" / "frontend" / "i18n" / name).read_text(encoding="utf-8"))
        for key in ("prepareSelected", "confirmPrepare", "preparing", "selectAllPage", "tooManySelected"):
            assert key in d, f"{name}: {key} yok"
        assert "{count}" in d["prepareSelected"] and "{count}" in d["confirmPrepare"]


def test_jobs_column_widths_match_checkbox_column():
    """Regresyon: checkbox sütunu eklenince nth-child genişlikleri 8 sütuna
    göre güncellenmeli, yoksa tablo sağa kaymış görünür."""
    import re

    tab = JOBS_TAB.read_text(encoding="utf-8")
    thead = tab.split("<thead>")[1].split("</thead>")[0]
    th_count = thead.count("<th")
    css = (ROOT / "services" / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    widths = [int(w) for w in re.findall(r"\.table-fixed\.jobs-table th:nth-child\(\d+\) \{ width: (\d+)%; \}", css)]
    assert len(widths) == th_count, f"CSS {len(widths)} sütun, tablo {th_count} sütun"
    assert sum(widths) == 100, f"sütun genişlikleri toplamı {sum(widths)}, 100 olmalı"
    assert widths[0] <= 5, "checkbox sütunu dar olmalı"
