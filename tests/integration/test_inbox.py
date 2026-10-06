"""F3: inbox sayaçları testi (SQLite, offline)."""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
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
    spec = importlib.util.spec_from_file_location("careerflow_api_inbox", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_inbox"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import Application, Base, Job, JobMatch  # noqa: E402

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
    now = datetime.now(timezone.utc)
    async with maker() as s:
        for i, st in enumerate(["REQUIRES_HUMAN", "REQUIRES_HUMAN", "READY_TO_SUBMIT", "FAILED", "CREATED", "SUBMITTED"]):
            j = Job(
                id=uuid4(), source="manual", source_job_id=f"ib-{i}", company="C",
                title="R", url=f"https://example.example/j/ib-{i}",
                job_fingerprint=f"fp-ib-{i}", status="NORMALIZED", created_at=now,
            )
            s.add(j)
            await s.flush()
            s.add(Application(
                id=uuid4(), job_id=j.id, candidate_id="cand-1",
                application_fingerprint=f"fp-ib-app-{i}", status=st,
            ))
        # 2 yeni + 1 eski QUALIFIED eşleşme.
        for i, age in enumerate([0, 1, 10]):
            j = Job(
                id=uuid4(), source="manual", source_job_id=f"ibq-{i}", company="Q",
                title="R", url=f"https://example.example/j/ibq-{i}",
                job_fingerprint=f"fp-ibq-{i}", status="QUALIFIED",
                created_at=now - timedelta(days=age),
            )
            s.add(j)
            await s.flush()
            s.add(JobMatch(
                id=uuid4(), job_id=j.id, overall_score=95.0, confidence=0.9,
                qualification_status="QUALIFIED",
            ))
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


def test_inbox_counts(client, seed):
    body = client.get("/api/v1/inbox").json()
    assert body == {
        "needs_you": 2,
        "ready": 1,
        "failed": 1,
        "to_prepare": 1,
        "new_strong_matches": 2,
    }
