"""Frontend layout + API-contract regression tests (static, offline).

Guards the stabilization fixes:
- every dashboard <table> must sit inside a horizontally scrollable
  `.table-scroll` container (otherwise wide tables clip action columns);
- tabs must be scrollable on narrow viewports;
- data tables must distinguish loading from empty states;
- every /api path the frontend fetches must exist as a backend route
  (frontend/backend contract check; /health-check is a Next.js rewrite
  to the API /health endpoint).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "services" / "frontend" / "app" / "page.js"
CSS = ROOT / "services" / "frontend" / "app" / "globals.css"
API = ROOT / "services" / "api" / "app" / "main.py"
NEXT_CONFIG = ROOT / "services" / "frontend" / "next.config.js"


def test_tables_scroll_inside_panel():
    src = PAGE.read_text(encoding="utf-8")
    tables = len(re.findall(r"<table>", src))
    wrappers = len(re.findall(r'className="table-scroll"', src))
    assert tables >= 4, f"expected at least 4 tables, found {tables}"
    assert wrappers >= tables, (
        f"every table needs a .table-scroll wrapper ({wrappers} wrappers, {tables} tables)"
    )


def test_scroll_css_rules_exist():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.table-scroll\s*\{[^}]*overflow-x:\s*auto", css), ".table-scroll needs overflow-x:auto"
    assert re.search(r"\.tabs\s*\{[^}]*overflow-x:\s*auto", css), ".tabs needs overflow-x:auto"
    assert re.search(r"\.tab\s*\{[^}]*white-space:\s*nowrap", css), ".tab needs white-space:nowrap"


def test_tables_show_loading_state():
    src = PAGE.read_text(encoding="utf-8")
    for component in ["JobsTab", "ApplicationsTab", "DocumentsTab", "EventsTab", "OverviewTab"]:
        assert re.search(rf"function {component}\(\{{[^)]*loading", src, re.IGNORECASE), (
            f"{component} must accept a loading prop"
        )
    assert src.count("Loading…") >= 4, "tables should render a Loading… state while fetching"


def test_frontend_api_paths_exist_in_backend():
    frontend_paths = set(re.findall(r'"(/api/[^"?]*)', PAGE.read_text(encoding="utf-8")))
    frontend_paths |= set(re.findall(r"'(/api/[^'?]*)", PAGE.read_text(encoding="utf-8")))
    backend_routes = set(re.findall(r'@app\.(?:get|post)\("([^"]*)"', API.read_text(encoding="utf-8")))
    # dynamic segments match any concrete value
    patterns = [re.sub(r"\{[^}]+\}", "[^/]+", r) + r"$" for r in backend_routes]
    missing = [p for p in sorted(frontend_paths) if not any(re.match(pat, p) for pat in patterns)]
    assert not missing, f"frontend calls unknown backend routes: {missing}"


def test_health_check_rewrite_preserved():
    config = NEXT_CONFIG.read_text(encoding="utf-8")
    assert '"/health-check"' in config and "/health" in config, (
        "the /health-check rewrite to the API /health endpoint must be preserved"
    )
    assert "API_INTERNAL_URL" in config


def test_documents_use_safe_download_not_raw_paths():
    src = PAGE.read_text(encoding="utf-8")
    assert "Artifact Path" not in src, "raw internal paths must not be the primary UI"
    assert src.count("Download") >= 1 and ">Open<" in src.replace("\n", ""), (
        "documents need visible Open/Download actions"
    )
    assert "document.download_url" in src, "artifact access must use the safe API download URL"


def test_download_endpoint_streams_safely():
    api = API.read_text(encoding="utf-8")
    assert '"/api/v1/documents/{document_id}/download"' in api
    assert "StreamingResponse" in api and "attachment;" in api
    assert "Document not found" in api  # 404 for unknown ids, no arbitrary object access
