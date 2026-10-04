"""T4(c) API-key + confirmation-gate tests (offline, static + unit)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "services" / "api" / "app" / "main.py"
ROUTERS = ROOT / "services" / "api" / "app" / "routers"


def _router_routes() -> set:
    """Router prefix'leriyle birlesmis tam yollari dondurur."""
    routes = set()
    for path in sorted(ROUTERS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        prefix = ""
        m = re.search(r'prefix="([^"]*)"', src)
        if m:
            prefix = m.group(1)
        for route in re.findall(r"@router\.(?:get|post|patch|put|delete)\(\"([^\"]*)\"", src):
            routes.add(prefix + route)
    return routes


def test_health_is_public_but_protected_routes_require_key():
    src = API.read_text(encoding="utf-8")
    # /health has no ApiKey dependency (public for LB / docker healthcheck).
    m = re.search(r'@app\.get\("/health"\)(.*?)(?=@app\.|\Z)', src, re.DOTALL)
    assert m and "ApiKey" not in m.group(1)
    # Every router carries the key at router level (Gorev 3); routes don't repeat it.
    for router_file in ROUTERS.glob("*.py"):
        if router_file.name == "__init__.py":
            continue
        rsrc = router_file.read_text(encoding="utf-8")
        assert "dependencies=[Depends(require_api_key)]" in rsrc, router_file.name
        assert "dependencies=[ApiKey]" not in rsrc, router_file.name
    for protected in ["/api/v1/status", "/api/v1/jobs", "/api/v1/applications", "/api/v1/events"]:
        assert protected in _router_routes(), protected


def test_fill_and_submit_require_explicit_confirmation():
    src = (ROUTERS / "pipeline.py").read_text(encoding="utf-8")
    assert 'CONFIRMATION_REQUIRED_ACTIONS = {"fill_applications", "submit_application"}' in src
    assert "HTTP_409_CONFLICT" in src
    assert "Explicit confirmation is required" in src


def test_api_key_rejects_wrong_key():
    import asyncio
    import sys

    sys.path.insert(0, str(ROOT / "services" / "api"))
    try:
        from app.security import require_api_key
        from fastapi import HTTPException

        from shared.config import settings

        settings.API_KEY = "test-key-12345678901234567890"
        try:
            asyncio.run(require_api_key("wrong"))
            raise AssertionError("wrong key must raise")
        except HTTPException as exc:
            assert exc.status_code == 401
        asyncio.run(require_api_key("test-key-12345678901234567890"))
    finally:
        if str(ROOT / "services" / "api") in sys.path:
            sys.path.remove(str(ROOT / "services" / "api"))
