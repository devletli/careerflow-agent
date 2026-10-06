"""Application lifecycle: status history + per-application document snapshot.

Offline (SQLite + mocked API key). Covers the P0 gaps:
- lifecycle_status / application_method / applied_at / next_action on Application
- application_status_history append-only audit
- application_documents authoritative snapshot (same doc -> many apps,
  app A = CV v4 while app B = CV v5 on the same job)
- timeline = created + attachments + status changes + pipeline events
- manual intake defaults to MANUAL/DRAFT, job user_status untouched pipeline status
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


def _load_api():
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_lifecycle", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_lifecycle"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import (  # noqa: E402
    Application,
    Base,
    Document,
    Job,
)

_api.app.dependency_overrides[require_api_key] = lambda: None


def _job(**kw):
    base = dict(
        id=uuid4(), source="manual", source_job_id=f"src-{uuid4().hex[:8]}",
        company="Bosch", title="DevOps Engineer", url="https://bosch.example/j/1",
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


def _doc(job_id, dtype="cv", lang="en", version=1, **kw):
    base = dict(
        id=uuid4(), job_id=job_id, application_id=None,
        type=dtype, language=lang, version=version,
        minio_bucket="docs", minio_key=f"k-{uuid4().hex}",
        mime_type="application/pdf", content_hash=f"h-{uuid4().hex}",
    )
    base.update(kw)
    return Document(**base)


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
        job = _job(company="Bosch", title="DevOps Engineer")
        s.add(job)
        await s.flush()
        ids["job"] = str(job.id)
        app_a = _app(job.id)
        app_b = _app(job.id)
        s.add_all([app_a, app_b])
        await s.flush()
        ids["app_a"] = str(app_a.id)
        ids["app_b"] = str(app_b.id)
        cv4 = _doc(job.id, version=4)
        cv5 = _doc(job.id, version=5)
        cl2 = _doc(job.id, dtype="cover_letter", version=2)
        s.add_all([cv4, cv5, cl2])
        await s.flush()
        ids["cv4"] = str(cv4.id)
        ids["cv5"] = str(cv5.id)
        ids["cl2"] = str(cl2.id)
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


def test_lifecycle_change_records_history_and_stamps_applied(client, seed):
    r = client.patch(
        f"/api/v1/applications/{seed['app_a']}",
        json={"lifecycle_status": "APPLIED", "lifecycle_note": "via portal"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_status"] == "APPLIED"
    assert r.json()["applied_at"] is not None
    detail = client.get(f"/api/v1/applications/{seed['app_a']}").json()
    assert detail["lifecycle_status"] == "APPLIED"
    assert len(detail["status_history"]) == 1
    assert detail["status_history"][0]["to_status"] == "APPLIED"
    # Second transition appends, first applied_at is kept.
    first_applied = detail["applied_at"]
    client.patch(f"/api/v1/applications/{seed['app_a']}", json={"lifecycle_status": "INTERVIEW"})
    detail2 = client.get(f"/api/v1/applications/{seed['app_a']}").json()
    assert [h["to_status"] for h in detail2["status_history"]] == ["APPLIED", "INTERVIEW"]
    assert detail2["applied_at"] == first_applied


def test_lifecycle_rejects_unknown_status(client, seed):
    r = client.patch(
        f"/api/v1/applications/{seed['app_a']}", json={"lifecycle_status": "HIRED_TOMORROW"}
    )
    assert r.status_code == 422


def test_document_snapshot_is_per_application_not_per_job(client, seed):
    # App A applies with CV v4, App B with CV v5 (same job).
    assert client.post(
        f"/api/v1/applications/{seed['app_a']}/documents",
        json={"document_id": seed["cv4"], "role": "CV"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/applications/{seed['app_b']}/documents",
        json={"document_id": seed["cv5"], "role": "CV"},
    ).status_code == 200
    det_a = client.get(f"/api/v1/applications/{seed['app_a']}").json()
    det_b = client.get(f"/api/v1/applications/{seed['app_b']}").json()
    assert [d["id"] for d in det_a["attached_documents"]] == [seed["cv4"]]
    assert [d["id"] for d in det_b["attached_documents"]] == [seed["cv5"]]
    # Both still see all job docs in the picker, but `linked` differs.
    linked_a = {d["id"] for d in det_a["documents"] if d["linked"]}
    linked_b = {d["id"] for d in det_b["documents"] if d["linked"]}
    assert seed["cv4"] in linked_a and seed["cv5"] not in linked_a
    assert seed["cv5"] in linked_b and seed["cv4"] not in linked_b
    # List view exposes the same snapshot.
    apps = {a["id"]: a for a in client.get("/api/v1/applications").json()["items"]}
    assert [d["id"] for d in apps[seed["app_a"]]["documents"]["attached"]] == [seed["cv4"]]


def test_same_document_can_attach_to_two_applications(client, seed):
    for app_id in (seed["app_a"], seed["app_b"]):
        r = client.post(
            f"/api/v1/applications/{app_id}/documents",
            json={"document_id": seed["cl2"], "role": "COVER_LETTER"},
        )
        assert r.status_code == 200, r.text
    det_a = client.get(f"/api/v1/applications/{seed['app_a']}").json()
    det_b = client.get(f"/api/v1/applications/{seed['app_b']}").json()
    assert seed["cl2"] in [d["id"] for d in det_a["attached_documents"]]
    assert seed["cl2"] in [d["id"] for d in det_b["attached_documents"]]
    # Detach from A only; B keeps its snapshot.
    assert client.delete(
        f"/api/v1/applications/{seed['app_a']}/documents/{seed['cl2']}"
    ).status_code == 200
    det_a2 = client.get(f"/api/v1/applications/{seed['app_a']}").json()
    det_b2 = client.get(f"/api/v1/applications/{seed['app_b']}").json()
    assert seed["cl2"] not in [d["id"] for d in det_a2["attached_documents"]]
    assert seed["cl2"] in [d["id"] for d in det_b2["attached_documents"]]


def test_next_action_and_method_persist(client, seed):
    r = client.patch(
        f"/api/v1/applications/{seed['app_a']}",
        json={
            "application_method": "MANUAL",
            "next_action": "Recruiter'a geri dön",
            "next_action_due_at": "2026-10-10T14:00:00+00:00",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["application_method"] == "MANUAL"
    assert r.json()["next_action"] == "Recruiter'a geri dön"
    detail = client.get(f"/api/v1/applications/{seed['app_a']}").json()
    assert detail["next_action_due_at"].startswith("2026-10-10")


def test_timeline_combines_created_attach_and_status(client, seed):
    client.post(
        f"/api/v1/applications/{seed['app_a']}/documents",
        json={"document_id": seed["cv4"], "role": "CV"},
    )
    client.patch(f"/api/v1/applications/{seed['app_a']}", json={"lifecycle_status": "APPLIED"})
    timeline = client.get(f"/api/v1/applications/{seed['app_a']}").json()["timeline"]
    kinds = [t["kind"] for t in timeline]
    assert "created" in kinds
    assert "document_attached" in kinds
    assert "status_change" in kinds


def test_job_user_status_does_not_touch_pipeline_status(client, seed):
    r = client.patch(f"/api/v1/jobs/{seed['job']}", json={"user_status": "ARCHIVED"})
    assert r.status_code == 200, r.text
    assert r.json()["user_status"] == "ARCHIVED"
    assert r.json()["status"] == "NORMALIZED"
    assert client.patch(f"/api/v1/jobs/{seed['job']}", json={"user_status": "NOPE"}).status_code == 422
