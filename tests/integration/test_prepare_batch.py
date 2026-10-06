"""F4: toplu "Hazırla" testi (SQLite + sahte Redis, offline).

- 21 id → 422 (sunucu Pydantic sınırı).
- NOT_QUALIFIED reddedilir; REVIEW bayraksız reddedilir, bayraklı kabul.
- İkinci eşzamanlı çağrı 409 (Redis NX kilidi).
- Idempotent: ikinci çağrı exists döner, yeni olay yayınlanmaz.
- Batch sonunda hiçbir fill/submit olayı yok.
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_api(name):
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api("careerflow_api_prepare")

from app.security import require_api_key  # noqa: E402
from shared.contracts.fingerprint import compute_application_fingerprint  # noqa: E402
from shared.db.models import Application, Base, Job, JobMatch  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


class _FakeRedis:
    def __init__(self, locked=False):
        self.d = {}
        self.locked = locked

    async def set(self, key, value, ex=None, nx=False):
        if nx and (key in self.d or self.locked):
            return None
        self.d[key] = value
        return True

    async def delete(self, key):
        self.d.pop(key, None)


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
    ids = {}
    async with maker() as s:
        for key, band, score in [
            ("qual", "QUALIFIED", 95.0),
            ("review", "REVIEW", 85.0),
            ("bad", "NOT_QUALIFIED", 10.0),
        ]:
            j = Job(
                id=uuid4(), source="manual", source_job_id=f"pb-{key}", company="C",
                title="R", url=f"https://example.example/j/pb-{key}",
                job_fingerprint=f"fp-pb-{key}", status="NORMALIZED",
            )
            s.add(j)
            await s.flush()
            s.add(JobMatch(
                id=uuid4(), job_id=j.id, overall_score=score, confidence=0.9,
                qualification_status=band,
            ))
            ids[key] = str(j.id)
        # Idempotency: qual-benzeri ikinci iş + önceden hazırlanmış uygulama.
        j2 = Job(
            id=uuid4(), source="manual", source_job_id="pb-dup", company="C",
            title="R", url="https://example.example/j/pb-dup",
            job_fingerprint="fp-pb-dup", status="NORMALIZED",
        )
        s.add(j2)
        await s.flush()
        s.add(JobMatch(
            id=uuid4(), job_id=j2.id, overall_score=96.0, confidence=0.9,
            qualification_status="QUALIFIED",
        ))
        ids["dup"] = str(j2.id)
        fp = compute_application_fingerprint("default_candidate", "fp-pb-dup")
        s.add(Application(
            id=uuid4(), job_id=j2.id, candidate_id="default_candidate",
            application_fingerprint=fp, status="CREATED",
        ))
        await s.commit()
    from shared.db.session import get_db_session

    async def _override():
        async with maker() as session:
            yield session
            await session.commit()

    _api.app.dependency_overrides[get_db_session] = _override
    yield ids
    _api.app.dependency_overrides.pop(get_db_session, None)
    await engine.dispose()


@pytest.fixture()
def client(seed):
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    fake = _FakeRedis()
    published = []

    async def _fake_redis():
        return fake

    async def _fake_publish(event, stream=None):
        published.append(event)
        return "msg-1"

    with (
        patch.object(_api.redis_bus, "get_redis", new=_fake_redis),
        patch.object(_api.redis_bus, "publish", new=_fake_publish),
        TestClient(_api.app) as c,
    ):
        c.fake_redis = fake
        c.published = published
        yield c


def test_21_ids_rejected_422(client, seed):
    r = client.post("/api/v1/jobs/prepare", json={"job_ids": [seed["qual"]] * 21})
    assert r.status_code == 422


def test_band_gates_and_accept(client, seed):
    body = client.post("/api/v1/jobs/prepare", json={"job_ids": [seed["qual"], seed["review"], seed["bad"]]}).json()
    by_job = {r["job_id"]: r for r in body["results"]}
    assert by_job[seed["qual"]]["result"] == "accepted"
    assert by_job[seed["review"]]["result"] == "rejected"
    assert by_job[seed["bad"]]["result"] == "rejected"
    # REVIEW bilinçli seçimle kabul edilir.
    body2 = client.post(
        "/api/v1/jobs/prepare", json={"job_ids": [seed["review"]], "include_review": True}
    ).json()
    assert body2["results"][0]["result"] == "accepted"
    # Idempotent: önceden hazırlanmış aynı fingerprint exists döner.
    body3 = client.post("/api/v1/jobs/prepare", json={"job_ids": [seed["dup"]]}).json()
    assert body3["results"][0]["result"] == "exists"


def test_concurrent_second_call_409(client, seed):
    from unittest.mock import patch

    async def _locked_redis():
        return _FakeRedis(locked=True)

    with patch.object(_api.redis_bus, "get_redis", new=_locked_redis):
        r = client.post("/api/v1/jobs/prepare", json={"job_ids": [seed["qual"]]})
    assert r.status_code == 409


def test_no_fill_or_submit_events(client, seed):
    client.post("/api/v1/jobs/prepare", json={"job_ids": [seed["qual"], seed["review"]], "include_review": True})
    assert client.published, "hazırlık zinciri olay yayınlamalı"
    for event in client.published:
        payload = event.payload or {}
        assert payload.get("action") not in {"fill_applications", "submit_application", "fill", "submit"}
        assert event.event_type not in {
            "application.filled.v1", "application.submitted.v1",
            "pipeline.fill.v1", "pipeline.submit.v1",
        }
    types = {e.event_type for e in client.published}
    assert types <= {"job.qualified.v1"}, f"beklenmeyen olaylar: {types}"
