"""GuiYama application-center API tests (offline, SQLite + mocked MinIO).

Covers: document filters (q/type/application_id) with application info and
is_latest, file endpoint inline/attachment, application filters + document
summary, application detail, manual link/unlink (+cross-job 422), notes,
manual URL create idempotency, and orphan documents rendering without error.
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))


def _load_api():
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_appcenter", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_appcenter"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import (  # noqa: E402
    Application,
    ApplicationAnswer,
    ApplicationQuestion,
    Base,
    Document,
    Job,
    JobMatch,
    PipelineEvent,
    Profile,
)

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
        profile = Profile(id=uuid4(), candidate_data={}, version=1, is_active=True)
        s.add(profile)
        job1 = Job(
            id=uuid4(), source="workable", source_job_id="ac-1", company="Acme",
            title="DevOps Engineer", url="https://acme.example/j/1",
            application_url="https://acme.example/j/1/apply",
            job_fingerprint="fp-acme-1", status="READY_TO_APPLY",
        )
        job2 = Job(
            id=uuid4(), source="manual", source_job_id="gx-1", company="Globex",
            title="Backend Engineer", url="https://globex.example/j/9",
            job_fingerprint="fp-globex-9", status="NORMALIZED",
        )
        s.add_all([job1, job2])
        app1 = Application(
            id=uuid4(), job_id=job1.id, candidate_id="cand-1",
            application_fingerprint="fp-app-1", status="READY_TO_APPLY",
        )
        s.add(app1)
        match = JobMatch(
            id=uuid4(), job_id=job1.id, overall_score=95.0, confidence=0.94,
            qualification_status="QUALIFIED", explanation="Overall Match Score: 95.0%",
        )
        s.add(match)
        cv1 = Document(
            id=uuid4(), job_id=job1.id, application_id=app1.id, type="cv",
            language="en", version=1, minio_bucket="b", minio_key="k/cv1.pdf",
            mime_type="application/pdf", content_hash="h1",
        )
        cv2 = Document(
            id=uuid4(), job_id=job1.id, application_id=app1.id, type="cv",
            language="en", version=2, minio_bucket="b", minio_key="k/cv2.pdf",
            mime_type="application/pdf", content_hash="h2",
        )
        orphan = Document(
            id=uuid4(), job_id=job1.id, application_id=None, type="cover_letter",
            language="en", version=1, minio_bucket="b", minio_key="k/cl.pdf",
            mime_type="application/pdf", content_hash="h3",
        )
        other = Document(
            id=uuid4(), job_id=job2.id, application_id=None, type="cv",
            language="en", version=1, minio_bucket="b", minio_key="k/gx.pdf",
            mime_type="application/pdf", content_hash="h4",
        )
        s.add_all([cv1, cv2, orphan, other])
        q1 = ApplicationQuestion(
            id=uuid4(), application_id=app1.id, question_key="email",
            question_text="Email", question_type="text", is_required=True,
            classification="SAFE_FACT", confidence=1.0,
        )
        s.add(q1)
        s.add(
            ApplicationAnswer(
                id=uuid4(), application_id=app1.id, question_id=q1.id,
                answer_value={"value": "ada@example.com"},
                answer_source="PROFILE_FACT", is_verified=True,
            )
        )
        s.add(
            PipelineEvent(
                id=uuid4(), event_id=uuid4(), event_type="job.qualified.v1",
                version="v1", correlation_id="corr-1", entity_id=str(app1.id),
                entity_type="application", payload={},
            )
        )
        await s.commit()
        ids = {
            "job1": job1.id, "job2": job2.id, "app1": app1.id,
            "cv1": cv1.id, "cv2": cv2.id, "orphan": orphan.id, "other": other.id,
        }
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
    from unittest.mock import MagicMock

    with patch.object(_api.minio_client, "download_bytes", new=MagicMock(return_value=b"%PDF-1.4")):
        yield TestClient(_api.app)


def test_documents_list_marks_latest_and_orphan(client, seed):
    body = client.get("/api/v1/documents").json()
    assert len(body) == 4
    by_id = {d["id"]: d for d in body}
    assert by_id[str(seed["cv2"])]["is_latest"] is True
    assert by_id[str(seed["cv1"])]["is_latest"] is False
    # Orphan renders with null application, no error.
    orphan = by_id[str(seed["orphan"])]
    assert orphan["application"] is None
    assert orphan["company"] == "Acme" and orphan["job_title"] == "DevOps Engineer"
    linked = by_id[str(seed["cv1"])]
    assert linked["application"] == {"id": str(seed["app1"]), "status": "READY_TO_APPLY"}


def test_documents_filters(client, seed):
    assert len(client.get("/api/v1/documents?type=cv").json()) == 3
    assert len(client.get("/api/v1/documents", params={"application_id": str(seed["app1"])}).json()) == 2
    assert len(client.get("/api/v1/documents?q=globex").json()) == 1
    assert client.get("/api/v1/documents?q=nonexistent-xyz").json() == []


def test_file_endpoint_inline_and_attachment(client, seed):
    inline = client.get(f"/api/v1/documents/{seed['cv1']}/file?download=0")
    assert inline.status_code == 200
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.headers["content-type"] == "application/pdf"
    attached = client.get(f"/api/v1/documents/{seed['cv1']}/file?download=1")
    assert attached.headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/v1/documents/{uuid4()}/file").status_code == 404


def test_applications_filters_and_document_summary(client, seed):
    body = client.get("/api/v1/applications").json()
    assert len(body) == 1
    app = body[0]
    assert app["match_score"] == 95.0
    assert app["documents"]["count"] == 3
    assert {d["type"] for d in app["documents"]["latest"]} == {"cv", "cover_letter"}
    assert client.get("/api/v1/applications", params={"q": "acme"}).json()
    assert client.get("/api/v1/applications", params={"q": "nope-xyz"}).json() == []
    assert client.get("/api/v1/applications", params={"status": "SUBMITTED"}).json() == []
    assert client.get("/api/v1/applications", params={"min_score": 99}).json() == []
    assert len(client.get("/api/v1/applications", params={"min_score": 90}).json()) == 1


def test_application_detail(client, seed):
    body = client.get(f"/api/v1/applications/{seed['app1']}").json()
    assert body["company"] == "Acme"
    assert body["match"]["qualification_status"] == "QUALIFIED"
    assert len(body["documents"]) == 3
    assert body["questions"][0]["answer"] == {
        "value": "ada@example.com", "source": "PROFILE_FACT", "is_verified": True,
    }
    assert body["events"][0]["correlation_id"] == "corr-1"
    assert client.get(f"/api/v1/applications/{uuid4()}").status_code == 404


def test_manual_link_unlink_and_cross_job_rejected(client, seed):
    # Link orphan -> app1 (same job).
    r = client.patch(
        f"/api/v1/applications/{seed['app1']}/documents/{seed['orphan']}",
        json={"application_id": str(seed["app1"])},
    )
    assert r.status_code == 200 and r.json()["application_id"] == str(seed["app1"])
    # Cross-job link rejected.
    r2 = client.patch(
        f"/api/v1/applications/{seed['app1']}/documents/{seed['other']}",
        json={"application_id": str(seed["app1"])},
    )
    assert r2.status_code == 422
    # Unlink.
    r3 = client.patch(
        f"/api/v1/applications/{seed['app1']}/documents/{seed['orphan']}",
        json={"application_id": None},
    )
    assert r3.json()["application_id"] is None


def test_notes_roundtrip(client, seed):
    r = client.patch(f"/api/v1/applications/{seed['app1']}", json={"notes": "Call on Monday"})
    assert r.status_code == 200 and r.json()["notes"] == "Call on Monday"
    assert client.get(f"/api/v1/applications/{seed['app1']}").json()["notes"] == "Call on Monday"


def test_backfill_document_application_links(client, seed):
    # Before backfill: orphan has application_id=None
    body = client.get("/api/v1/documents").json()
    assert any(d["application"] is None for d in body)

    # Run backfill
    r = client.patch("/api/v1/documents/backfill")
    assert r.status_code == 200
    data = r.json()
    assert data["linked"] >= 0

    # After backfill: orphan should be linked to app1 (only app for job1)
    body = client.get("/api/v1/documents").json()
    by_id = {d["id"]: d for d in body}
    orphan = by_id[str(seed["orphan"])]
    # Since only app1 exists for job1, orphan should now be linked
    assert orphan["application"] == {"id": str(seed["app1"]), "status": "READY_TO_APPLY"}
    # cv1 and cv2 were already linked, other has no app for job2
    assert by_id[str(seed["cv1"])]["application"]["id"] == str(seed["app1"])
    assert by_id[str(seed["cv2"])]["application"]["id"] == str(seed["app1"])
    assert by_id[str(seed["other"])]["application"] is None  # job2 has no application


def test_documents_list_with_application_id_filter(client, seed):
    # Test filtering by application_id
    body = client.get("/api/v1/documents", params={"application_id": str(seed["app1"])}).json()
    assert len(body) == 2  # cv1, cv2
    for d in body:
        assert d["application"] == {"id": str(seed["app1"]), "status": "READY_TO_APPLY"}


def test_applications_with_document_summary_and_filters(client, seed):
    body = client.get("/api/v1/applications").json()
    assert len(body) == 1
    app = body[0]
    assert app["match_score"] == 95.0
    assert app["documents"]["count"] == 3
    assert {d["type"] for d in app["documents"]["latest"]} == {"cv", "cover_letter"}
    # Filters
    assert client.get("/api/v1/applications", params={"q": "acme"}).json()
    assert client.get("/api/v1/applications", params={"q": "nope-xyz"}).json() == []
    assert client.get("/api/v1/applications", params={"status": "SUBMITTED"}).json() == []
    assert client.get("/api/v1/applications", params={"min_score": 99}).json() == []
    assert len(client.get("/api/v1/applications", params={"min_score": 90}).json()) == 1


def test_application_detail_includes_documents_and_form(client, seed):
    body = client.get(f"/api/v1/applications/{seed['app1']}").json()
    assert body["company"] == "Acme"
    assert body["match"]["qualification_status"] == "QUALIFIED"
    assert len(body["documents"]) == 3
    assert body["questions"][0]["answer"] == {
        "value": "ada@example.com", "source": "PROFILE_FACT", "is_verified": True,
    }
    assert body["events"][0]["correlation_id"] == "corr-1"


def test_manual_link_unlink_and_cross_job_rejected(client, seed):
    # Link orphan -> app1 (same job).
    r = client.patch(
        f"/api/v1/applications/{seed['app1']}/documents/{seed['orphan']}",
        json={"application_id": str(seed["app1"])},
    )
    assert r.status_code == 200 and r.json()["application_id"] == str(seed["app1"])
    # Cross-job link rejected.
    r2 = client.patch(
        f"/api/v1/applications/{seed['app1']}/documents/{seed['other']}",
        json={"application_id": str(seed["app1"])},
    )
    assert r2.status_code == 422
    # Unlink.
    r3 = client.patch(
        f"/api/v1/applications/{seed['app1']}/documents/{seed['orphan']}",
        json={"application_id": None},
    )
    assert r3.json()["application_id"] is None


def test_notes_roundtrip(client, seed):
    r = client.patch(f"/api/v1/applications/{seed['app1']}", json={"notes": "Call on Monday"})
    assert r.status_code == 200 and r.json()["notes"] == "Call on Monday"
    assert client.get(f"/api/v1/applications/{seed['app1']}").json()["notes"] == "Call on Monday"


def test_manual_create_idempotent(client):
    first = client.post("/api/v1/applications/manual", json={"url": "https://example.com/jobs/42"})
    assert first.status_code == 201 and first.json()["created"] is True
    app_id = first.json()["application"]["id"]
    second = client.post("/api/v1/applications/manual", json={"url": "https://example.com/jobs/42"})
    assert second.status_code == 200 and second.json()["created"] is False
    assert second.json()["application"]["id"] == app_id
    assert client.post("/api/v1/applications/manual", json={"url": ""}).status_code == 422


def test_orphan_documents_render_without_error(client, seed):
    """Orphan documents (no application) should render without error in UI."""
    body = client.get("/api/v1/documents").json()
    orphan_entries = [d for d in body if d["application"] is None]
    assert len(orphan_entries) >= 1
    # Each orphan should have company and job_title fields
    for d in orphan_entries:
        assert d.get("company")
        assert d.get("job_title")
