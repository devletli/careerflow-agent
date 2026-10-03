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
    assert "table-scroll" not in src, (
        "tables must fit the viewport via responsive columns, not scroll containers"
    )
    tables = len(re.findall(r"<table", src))
    responsive = len(re.findall(r'<table className="responsive', src))
    assert tables >= 4, f"expected at least 4 tables, found {tables}"
    assert responsive >= tables, "every dashboard table must use the responsive layout"
    labels = len(re.findall(r"data-label=", src))
    assert labels >= 20, f"stacked mobile rows need data-labels, found {labels}"


def test_scroll_css_rules_exist():
    css = CSS.read_text(encoding="utf-8")
    assert ".table-scroll" not in css, "no scroll-container workaround may remain in CSS"
    assert re.search(r"\.tabs\s*\{[^}]*overflow-x:\s*auto", css), (
        ".tabs nav strip stays scrollable so all tabs remain reachable on narrow screens"
    )
    assert re.search(r"\.tabs\s*\{[^}]*flex-shrink:\s*0", css), (
        ".tabs is a flex item of the 100vh app shell and a scroll container, "
        "so it must not shrink (otherwise it collapses to 1px and tabs vanish)"
    )
    assert re.search(r"\.tab-body\s*\{[^}]*overflow-y:\s*auto", css), (
        "tab content must scroll inside .tab-body so the browser page never scrolls"
    )
    assert re.search(r"\.tab-body\s*\{[^}]*flex:\s*1", css), (
        ".tab-body must fill the remaining viewport height"
    )
    assert '<div className="tab-body">' in PAGE.read_text(encoding="utf-8"), (
        "tab panels must render inside .tab-body"
    )
    assert re.search(r"\.tab\s*\{[^}]*white-space:\s*nowrap", css), ".tab needs white-space:nowrap"
    assert "@media (max-width:" in css and "table.responsive" in css, (
        "narrow viewports must stack table rows instead of scrolling"
    )


def test_action_cells_keep_buttons_visible():
    css = CSS.read_text(encoding="utf-8")
    src = PAGE.read_text(encoding="utf-8")
    assert "application-actions" in src and "document-actions" in src
    assert re.search(r"\.application-actions\s*\{[^}]*flex-wrap:\s*wrap", css), (
        "action buttons must wrap instead of clipping"
    )
    assert "flex-shrink: 0" in css, "action buttons must not shrink"


def test_theme_toggle_and_persistence():
    src = PAGE.read_text(encoding="utf-8")
    assert "useTheme" in src and "ai-job-agent-theme" in src
    assert 'aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}' in src
    assert "localStorage.setItem" in src
    assert "<ThemeToggle" in src
    layout = (ROOT / "services" / "frontend" / "app" / "layout.js").read_text(encoding="utf-8")
    assert "ai-job-agent-theme" in layout and "prefers-color-scheme" in layout, (
        "an inline startup script must apply the stored/system theme before first paint"
    )


def test_dark_theme_variables():
    css = CSS.read_text(encoding="utf-8")
    assert '[data-theme="dark"]' in css
    dark_block = css.split('[data-theme="dark"]', 1)[1]
    for var in ["--panel:", "--text:", "--border:", "--accent:"]:
        assert var in dark_block, f"dark theme must override {var}"
    assert "color-scheme: dark" in dark_block


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
    backend_routes = set(re.findall(r'@app\.(?:get|post|patch|put|delete)\("([^"]*)"', API.read_text(encoding="utf-8")))
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
    detail = (ROOT / "services" / "frontend" / "app" / "applications" / "[id]" / "page.js").read_text(encoding="utf-8")
    for component in (src, detail):
        assert "Artifact Path" not in component, "raw internal paths must not be the primary UI"
        for leaked in ("minio_key", "minio_bucket", "s3://", ":9000"):
            assert leaked not in component.lower(), f"MinIO reference may not reach the browser: {leaked}"
    # Documents table links through the safe /file endpoint (view), detail
    # page adds open/download/link actions via STRINGS (i18n, no hardcoding).
    assert "view_url" in src and "/file?download=0" in src
    assert "STRINGS.viewFile" in src
    assert "doc.download_url" in detail and "STRINGS.download" in detail


def test_download_endpoint_streams_safely():
    api = API.read_text(encoding="utf-8")
    assert '"/api/v1/documents/{document_id}/download"' in api
    assert "StreamingResponse" in api and "attachment;" in api
    assert "Document not found" in api  # 404 for unknown ids, no arbitrary object access


def test_gui_action_contract_explicit():
    """GUI must call onExecute(a, action) with an explicit semantic action.

    Regression for yama.md P0: Prepare/Submit/Retry/Continue must not share
    one implicit onSubmit handler, and per-row actions must come from
    getAvailableActions(application) — never from submittingApplicationId.
    """
    src = PAGE.read_text(encoding="utf-8")
    for action in ("prepare", "submit", "retry", "continue"):
        assert f'onExecute(a, "{action}")' in src, f"missing explicit onExecute call for {action}"
    assert "onClick={() => onSubmit(a)}" not in src, "implicit onSubmit handler must not remain"
    assert "function getAvailableActions(application)" in src
    assert "submittingApplicationId" not in src, "row actions must not depend on submittingApplicationId"
    api = API.read_text(encoding="utf-8")
    assert '"/api/v1/applications/{application_id}/execute"' in api
    assert "prepare" in api and "retry" in api and "continue" in api
