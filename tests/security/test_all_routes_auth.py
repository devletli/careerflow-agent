"""Gorev 3: hicbir /api route'u anahtarsiz acik kalmasin (canli TestClient).

openapi yuzeyindeki her /api path+method, anahtar yoksa VE yanlis
anahtarla 401 dondurmeli. /health bilerek disarida (public probe).
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))


def _load_api():
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_routerauth", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_routerauth"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from shared.config import settings  # noqa: E402

UUID0 = "00000000-0000-0000-0000-000000000000"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    settings.API_KEY = SecretStr("test-key-12345678901234567890")
    with TestClient(_api.app) as c:
        yield c


def test_every_api_route_rejects_missing_or_wrong_key(client):
    checked = 0
    for path, methods in _api.app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        url = re.sub(r"\{[^}]+\}", UUID0, path)
        for method in methods:
            if method.upper() not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                continue
            for headers in ({}, {"X-API-Key": "wrong"}):
                r = client.request(method.upper(), url, headers=headers)
                assert r.status_code == 401, f"{method.upper()} {path} {headers} -> {r.status_code}"
            checked += 1
    assert checked > 10  # route kesfi bozulursa test sessizce gecmesin


def test_health_stays_public(client):
    r = client.get("/health")
    assert r.status_code in (200, 503)
