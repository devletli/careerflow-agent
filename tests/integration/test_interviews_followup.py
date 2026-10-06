"""Interviews + follow-up + archive filters (offline).

SQLite + mocked API key. Covers:
- interview CRUD + 404/422 contracts
- scheduling moves DRAFT/PREPARED/APPLIED -> INTERVIEW (history recorded)
- no lifecycle downgrade from OFFER
- upcoming filter (PENDING + future only)
- timeline includes interviews
- application list filters: lifecycle_status, overdue
- job filters: user_status, exclude_archived; unarchive via null
- deleting an application cascades its interviews
"""
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
    spec = importlib.util.spec_from_file_location("careerflow_api_interviews", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_interviews"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import Application, Base, Interview, Job  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


def _job(**kw):
    base = dict(
        id=uuid4(), source="manual", source_job_id=f"src-{uuid4().hex[:8]}",
        company="BMW", title="Senior DevOps", url="https://bmw.example/j/1",
        job_fingerprint=f"fp-{uuid4().hex}", status="NORMALIZED",
    )
    base.update(kw)
    return Job(**base)


def _app(job_id, **kw):
    base = dict(
        id=uuid4(), job_id=job_id, candidate_id="cand-1",
        application_fingerprint=f"afp-{uuid4().hex}", status="CREATED",
    )
    base.update(kw)
    return Application(**base)


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
        job = _job()
        s.add(job)
        await s.flush()
        ids["job"] = str(job.id)
        app = _app(job.id, lifecycle_status="APPLIED")
        other = _app(job.id, lifecycle_status="DRAFT",
                     next_action="Recruiter'a geri dön",
                     next_action_due_at=datetime.now(timezone.utc) - timedelta(days=2))
        s.add_all([app, other])
        await s.flush()
        ids["app"] = str(app.id)
        ids["other"] = str(other.id)
        past = Interview(id=uuid4(), application_id=app.id,
                         scheduled_at=datetime.now(timezone.utc) - timedelta(days=1),
                         round="HR Call", result="PENDING")
        s.add(past)
        await s.flush()
        ids["past_interview"] = str(past.id)
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
    yield __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(_api.app)


def _future_iso(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_create_interview_moves_lifecycle_and_records_history(client, seed):
    r = client.post(
        f"/api/v1/applications/{seed['app']}/interviews",
        json={"scheduled_at": _future_iso(), "round": "Technical Interview",
              "mode": "Teams", "interviewer": "Max Mustermann",
              "notes": "Kubernetes + AWS + CI/CD questions"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["round"] == "Technical Interview"
    assert body["result"] == "PENDING"
    detail = client.get(f"/api/v1/applications/{seed['app']}").json()
    assert detail["lifecycle_status"] == "INTERVIEW"
    assert detail["status_history"][-1]["to_status"] == "INTERVIEW"
    assert len(detail["interviews"]) == 2
    kinds = [t["kind"] for t in detail["timeline"]]
    assert "interview" in kinds


def test_create_interview_rejects_unknown_result(client, seed):
    r = client.post(
        f"/api/v1/applications/{seed['app']}/interviews", json={"result": "HIRED"}
    )
    assert r.status_code == 422


def test_create_interview_unknown_application_404(client):
    r = client.post(f"/api/v1/applications/{uuid4()}/interviews", json={})
    assert r.status_code == 404


def test_interview_does_not_downgrade_offer(client, seed):
    client.patch(f"/api/v1/applications/{seed['app']}", json={"lifecycle_status": "OFFER"})
    client.post(f"/api/v1/applications/{seed['app']}/interviews",
                json={"scheduled_at": _future_iso()})
    assert client.get(f"/api/v1/applications/{seed['app']}").json()["lifecycle_status"] == "OFFER"


def test_upcoming_lists_only_pending_future(client, seed):
    client.post(f"/api/v1/applications/{seed['app']}/interviews",
                json={"scheduled_at": _future_iso(), "round": "Onsite"})
    rows = client.get("/api/v1/interviews?upcoming=true").json()
    ids = [r["id"] for r in rows]
    assert seed["past_interview"] not in ids
    assert len(ids) == 1
    assert rows[0]["company"] == "BMW"
    # Cancelling removes it from upcoming.
    client.patch(f"/api/v1/interviews/{ids[0]}", json={"result": "CANCELLED"})
    assert client.get("/api/v1/interviews?upcoming=true").json() == []


def test_update_and_delete_interview(client, seed):
    r = client.patch(f"/api/v1/interviews/{seed['past_interview']}",
                     json={"result": "PASSED", "notes": "Strong Kubernetes answers"})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "PASSED"
    assert r.json()["notes"] == "Strong Kubernetes answers"
    assert client.patch(f"/api/v1/interviews/{uuid4()}", json={"result": "PASSED"}).status_code == 404
    assert client.delete(f"/api/v1/interviews/{seed['past_interview']}").status_code == 200
    assert client.delete(f"/api/v1/interviews/{seed['past_interview']}").status_code == 404


def test_application_filters_lifecycle_and_overdue(client, seed):
    by_life = client.get("/api/v1/applications?lifecycle_status=applied").json()
    assert {a["id"] for a in by_life} == {seed["app"]}
    overdue = client.get("/api/v1/applications?overdue=true").json()
    assert {a["id"] for a in overdue} == {seed["other"]}
    assert overdue[0]["next_action"] == "Recruiter'a geri dön"


def test_job_archive_filter_and_unarchive(client, seed):
    assert client.patch(f"/api/v1/jobs/{seed['job']}", json={"user_status": "ARCHIVED"}).status_code == 200
    assert client.get("/api/v1/jobs?exclude_archived=true").json()["items"] == []
    assert len(client.get("/api/v1/jobs?user_status=archived").json()["items"]) == 1
    # Unarchive via null clears the flag without touching pipeline status.
    r = client.patch(f"/api/v1/jobs/{seed['job']}", json={"user_status": None})
    assert r.status_code == 200, r.text
    assert r.json()["user_status"] is None
    assert r.json()["status"] == "NORMALIZED"
    assert len(client.get("/api/v1/jobs?exclude_archived=true").json()["items"]) == 1


def test_delete_application_cascades_interviews(client, seed):
    assert client.delete(f"/api/v1/applications/{seed['app']}").status_code == 200
    assert client.get(f"/api/v1/interviews?application_id={seed['app']}").json() == []
