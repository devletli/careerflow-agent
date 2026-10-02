"""Minimal API smoke/performance regression test.

Exercises the REAL FastAPI application (services/api/app/main.py) with
external dependencies mocked out — no database, Redis, MinIO, or API keys
required. This is a smoke test, NOT production load testing: a small burst
of read-only requests with generous timing bounds.
"""
import importlib.util
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))


def _load_api():
    # Unique module name: every service uses a bare `app` package.
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_main", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_main"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


@pytest.fixture()
def client():
    with (
        patch.object(_api, "check_db_health", new=AsyncMock(return_value=True)),
        patch.object(_api.redis_bus, "ping", new=AsyncMock(return_value=True)),
        patch.object(_api.minio_client, "check_health", return_value=True),
    ):
        yield TestClient(_api.app)


def test_health_endpoint_ok(client):
    started = time.perf_counter()
    response = client.get("/health")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"] == {"postgres": True, "redis": True, "minio": True}
    assert elapsed < 5.0, f"/health took {elapsed:.2f}s"


def test_status_endpoint_shape(client):
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    for key in ("service", "version", "automation_mode", "auto_submit", "min_match_score"):
        assert key in body, f"missing status key {key}"
    assert body["service"] == "api"


def test_read_burst_latency_regression(client):
    """20 concurrent read-only requests: all must succeed within generous bounds."""
    def one(_):
        started = time.perf_counter()
        response = client.get("/api/v1/status")
        return response.status_code, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(one, range(20)))

    assert all(code == 200 for code, _ in results)
    p95 = statistics.quantiles([lat for _, lat in results], n=20)[18]
    assert p95 < 2.0, f"p95 latency {p95:.2f}s exceeds 2s smoke budget"


def test_api_key_enforcement():
    """Protected routes reject missing/wrong keys; /health stays public."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    _api.app.dependency_overrides.clear()
    try:
        with (
            patch.object(_api, "check_db_health", new=AsyncMock(return_value=True)),
            patch.object(_api.redis_bus, "ping", new=AsyncMock(return_value=True)),
            patch.object(_api.minio_client, "check_health", return_value=True),
        ):
            client = TestClient(_api.app, raise_server_exceptions=False)
            assert client.get("/health").status_code == 200
            assert client.get("/api/v1/status").status_code == 401
            assert client.get("/api/v1/status", headers={"X-API-Key": "wrong"}).status_code == 401
            assert client.get("/api/v1/jobs").status_code == 401
    finally:
        _api.app.dependency_overrides[require_api_key] = lambda: None
