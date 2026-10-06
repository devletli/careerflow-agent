"""F5: skor dağılımı testi (SQLite, offline).

- 100 son kovada (kova 9), 0 ilk kovada, boş kovalar sıfır dolgulu.
- Eşleşme yokken 10 sıfırlı kova; threshold yalnızca gösterim.
"""
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))


def _load_api(name):
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api("careerflow_api_stats")

from app.security import require_api_key  # noqa: E402
from shared.config import settings  # noqa: E402
from shared.db.models import Base, Job, JobMatch  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


async def _maker():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)


def _override_app(maker):
    from shared.db.session import get_db_session

    async def _override():
        async with maker() as session:
            yield session
            await session.commit()

    _api.app.dependency_overrides[get_db_session] = _override


@pytest.fixture()
async def seed():
    engine, maker = await _maker()
    async with maker() as s:
        for i, (score, band) in enumerate([
            (0.0, "NOT_QUALIFIED"), (5.0, "NOT_QUALIFIED"), (85.0, "REVIEW"),
            (95.0, "QUALIFIED"), (100.0, "QUALIFIED"),
        ]):
            j = Job(
                id=uuid4(), source="manual", source_job_id=f"sd-{i}", company="C",
                title="R", url=f"https://example.example/j/sd-{i}",
                job_fingerprint=f"fp-sd-{i}", status="NORMALIZED",
            )
            s.add(j)
            await s.flush()
            s.add(JobMatch(
                id=uuid4(), job_id=j.id, overall_score=score, confidence=0.9,
                qualification_status=band,
            ))
        await s.commit()
    _override_app(maker)
    yield
    _api.app.dependency_overrides.pop(
        __import__("shared.db.session", fromlist=["get_db_session"]).get_db_session, None
    )
    await engine.dispose()


@pytest.fixture()
async def empty_seed():
    engine, maker = await _maker()
    _override_app(maker)
    yield
    _api.app.dependency_overrides.pop(
        __import__("shared.db.session", fromlist=["get_db_session"]).get_db_session, None
    )
    await engine.dispose()


@pytest.fixture()
def client(seed):
    from fastapi.testclient import TestClient

    with TestClient(_api.app) as c:
        yield c


@pytest.fixture()
def empty_client(empty_seed):
    from fastapi.testclient import TestClient

    with TestClient(_api.app) as c:
        yield c


def test_buckets_bands_max_threshold(client, seed):
    body = client.get("/api/v1/stats/score-distribution").json()
    assert len(body["buckets"]) == 10
    by_from = {b["from"]: b["count"] for b in body["buckets"]}
    assert by_from[0] == 2  # 0.0 ve 5.0
    assert by_from[80] == 1  # REVIEW 85
    assert by_from[90] == 2  # 95 ve 100 son kovada
    assert sum(by_from.values()) == 5
    assert all(v == 0 for k, v in by_from.items() if k not in (0, 80, 90))
    assert body["bands"] == {"NOT_QUALIFIED": 2, "REVIEW": 1, "QUALIFIED": 2}
    assert body["max_score"] == 100.0
    assert body["scored"] == 5
    # Eşik yalnızca gösterim: ayar değerinin aynısı, davranış değişikliği yok.
    assert body["threshold"] == settings.MIN_MATCH_SCORE


def test_empty_distribution_is_zero_filled(empty_client, empty_seed):
    body = empty_client.get("/api/v1/stats/score-distribution").json()
    assert len(body["buckets"]) == 10
    assert all(b["count"] == 0 for b in body["buckets"])
    assert body["bands"] == {}
    assert body["max_score"] is None
    assert body["scored"] == 0
