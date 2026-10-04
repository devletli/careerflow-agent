"""GuiYama frontend tests (offline, static).

Application is the central record: tables link applications <-> documents
through safe API URLs, search/filter boxes exist, the detail route renders
all sections, and every new string lives in the i18n files.
"""
import json
import re
from pathlib import Path

from tests.unit._frontend_src import read_frontend_sources

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "services" / "frontend" / "app" / "page.js"
DETAIL = ROOT / "services" / "frontend" / "app" / "applications" / "[id]" / "page.js"
I18N = ROOT / "services" / "frontend" / "i18n"


def test_document_file_link_points_to_file_endpoint():
    src = read_frontend_sources()
    assert "/api/v1/documents/${d.id}/file?download=0" in src
    assert 'href={`/applications/${a.id}`}' in src
    assert 'href={`/applications/${document.application.id}`}' in src


def test_tables_have_search_and_filters():
    src = read_frontend_sources()
    assert src.count("<SearchBar") >= 3
    assert "distinctStatuses" in src
    assert "showScore" in src


def test_detail_route_covers_all_sections():
    assert DETAIL.exists()
    src = DETAIL.read_text(encoding="utf-8")
    for marker in (
        "/api/v1/applications/${id}",
        "STRINGS.formAnalysis",
        "STRINGS.timeline",
        "STRINGS.notes",
        "STRINGS.regenerate",
        "STRINGS.linkHere",
        "STRINGS.unlink",
        "/documents/${doc.id}",
    ):
        assert marker in src, f"detail page missing: {marker}"


def test_no_hardcoded_dashboard_strings_in_new_ui():
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    tr = json.loads((I18N / "tr.json").read_text(encoding="utf-8"))
    assert set(en) == set(tr)
    page = read_frontend_sources()
    detail = DETAIL.read_text(encoding="utf-8")
    for literal in (
        "Search…", "Ara…", "Unlinked", "Bağlantısız", "Details", "Detay",
        "Add via URL", "URL ile ekle", "Back to Applications",
    ):
        assert literal not in page and literal not in detail, f"hardcoded: {literal}"
    # Placeholders still match across locales.
    for key, value in en.items():
        if isinstance(value, str):
            assert set(re.findall(r"\{\w+\}", value)) == set(re.findall(r"\{\w+\}", tr[key]))


def test_url_dialog_posts_to_manual_endpoint():
    src = read_frontend_sources()
    assert "/api/v1/applications/manual" in src
    assert "STRINGS.addViaUrl" in src and "STRINGS.urlDialogTitle" in src
