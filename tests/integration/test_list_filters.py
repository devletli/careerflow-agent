"""Faz 2B: liste uclarinda ?q= (jobs, events) filtre testleri (SQLite, offline)."""
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


def _load_api():
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_listfilters", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_listfilters"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import Base, Job, PipelineEvent, Profile  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


@pytest.fixture()
async def seed():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as s:
        s.add(Profile(id=uuid4(), candidate_data={}, version=1, is_active=True))
        s.add(
            Job(
                id=uuid4(), source="workable", source_job_id="j-1", company="Acme",
                title="DevOps Engineer", url="https://acme.example/j/1",
                job_fingerprint="fp-1", status="NORMALIZED",
            )
        )
        s.add(
            Job(
                id=uuid4(), source="manual", source_job_id="j-2", company="Globex",
                title="Backend Engineer", url="https://globex.example/j/9",
                job_fingerprint="fp-2", status="NORMALIZED",
            )
        )
        s.add(
            PipelineEvent(
                id=uuid4(), event_id=uuid4(), event_type="job.discovered.v1",
                version="v1", correlation_id="corr-acme", idempotency_key="idem-acme",
                entity_id="entity-1",
                entity_type="job", payload={},
            )
        )
        s.add(
            PipelineEvent(
                id=uuid4(), event_id=uuid4(), event_type="job.matched.v1",
                version="v1", correlation_id="corr-globex", idempotency_key="idem-globex",
                entity_id="entity-2",
                entity_type="job", payload={},
            )
        )
        await s.commit()
    from shared.db.session import get_db_session

    async def _override():
        async with maker() as session:
            yield session
            await session.commit()

    _api.app.dependency_overrides[get_db_session] = _override
    yield
    _api.app.dependency_overrides.pop(get_db_session, None)
    await engine.dispose()


@pytest.fixture()
def client(seed):
    from fastapi.testclient import TestClient

    with TestClient(_api.app) as c:
        yield c


def test_jobs_q_filters_company(client, seed):
    body = client.get("/api/v1/jobs", params={"q": "acme"}).json()
    assert [j["company"] for j in body["items"]] == ["Acme"]
    assert len(client.get("/api/v1/jobs").json()["items"]) == 2


def test_jobs_q_matches_title_and_url(client, seed):
    assert len(client.get("/api/v1/jobs", params={"q": "backend"}).json()["items"]) == 1
    assert len(client.get("/api/v1/jobs", params={"q": "globex.example"}).json()["items"]) == 1
    assert client.get("/api/v1/jobs", params={"q": "no-such-thing"}).json()["items"] == []


def test_events_q_filters_type_and_correlation(client, seed):
    body = client.get("/api/v1/events", params={"q": "discovered"}).json()
    assert [e["event_type"] for e in body] == ["job.discovered.v1"]
    body = client.get("/api/v1/events", params={"q": "corr-globex"}).json()
    assert [e["correlation_id"] for e in body] == ["corr-globex"]
    assert len(client.get("/api/v1/events").json()) == 2
