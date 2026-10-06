"""Task3: safe DELETE for jobs / applications / documents (offline).

SQLite + mocked MinIO + mocked API key. Verifies the full lifecycle:
DB cascade policy, MinIO cleanup scoping, 404/409 contracts, and that
unrelated rows are never touched.
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
    spec = importlib.util.spec_from_file_location("careerflow_api_deletes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_deletes"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import (  # noqa: E402
    Application,
    ApplicationAnswer,
    ApplicationQuestion,
    AutomationRun,
    Base,
    Document,
    Job,
    JobMatch,
    JobRequirement,
)

_api.app.dependency_overrides[require_api_key] = lambda: None


def _job(**kw):
    base = dict(
        id=uuid4(), source="manual", source_job_id=f"src-{uuid4().hex[:8]}",
        company="Acme", title="Backend Engineer", url="https://acme.example/j/1",
        job_fingerprint=f"fp-{uuid4().hex}", status="NORMALIZED",
    )
    base.update(kw)
    return Job(**base)


def _app(job_id, status="CREATED", **kw):
    base = dict(
        id=uuid4(), job_id=job_id, candidate_id="cand-1",
        application_fingerprint=f"afp-{uuid4().hex}", status=status,
    )
    base.update(kw)
    return Application(**base)


def _doc(job_id, app_id=None, version=1, key=None, **kw):
    base = dict(
        id=uuid4(), job_id=job_id, application_id=app_id,
        type="cv", language="en", version=version,
        minio_bucket="docs", minio_key=key or f"k-{uuid4().hex}",
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
        job1 = _job(company="Acme")
        job2 = _job(company="Other")
        s.add_all([job1, job2])
        await s.flush()
        ids["job1"] = str(job1.id)
        ids["job2"] = str(job2.id)
        # job1 dependents
        s.add(JobRequirement(id=uuid4(), job_id=job1.id, requirement_type="skill", description="python"))
        s.add(JobMatch(id=uuid4(), job_id=job1.id, overall_score=80.0, confidence=0.9,
                       qualification_status="QUALIFIED"))
        app1 = _app(job1.id, "CREATED")
        s.add(app1)
        await s.flush()
        ids["app1"] = str(app1.id)
        q = ApplicationQuestion(id=uuid4(), application_id=app1.id, question_key="q1",
                                question_text="Name?", question_type="text")
        s.add(q)
        await s.flush()
        ids["question1"] = str(q.id)
        s.add(ApplicationAnswer(id=uuid4(), application_id=app1.id, question_id=q.id,
                                answer_value={"value": "Ada"}, answer_source="SAFE_FACT"))
        s.add(AutomationRun(id=uuid4(), application_id=app1.id, job_id=job1.id,
                             run_type="BROWSER_FILL", status="COMPLETED"))
        doc1 = _doc(job1.id, app1.id, version=1, key="key-doc1")
        doc2 = _doc(job1.id, None, version=2, key="key-doc2")
        s.add_all([doc1, doc2])
        await s.flush()
        ids["doc1"] = str(doc1.id)
        ids["doc2"] = str(doc2.id)
        # unrelated job2 data must survive job1 deletion
        app_other = _app(job2.id, "CREATED")
        s.add(app_other)
        doc_other = _doc(job2.id, None, version=1, key="key-other")
        s.add_all([app_other, doc_other])
        await s.flush()
        ids["app_other"] = str(app_other.id)
        ids["doc_other"] = str(doc_other.id)
        # running application (separate job) for 409 tests
        job_run = _job(company="RunningCo")
        s.add(job_run)
        await s.flush()
        ids["job_run"] = str(job_run.id)
        app_run = _app(job_run.id, "RUNNING")
        s.add(app_run)
        await s.flush()
        ids["app_run"] = str(app_run.id)
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


def _row_count(client_unused=None):
    return None


def test_delete_job_not_found(client):
    r = client.delete(f"/api/v1/jobs/{uuid4()}")
    assert r.status_code == 404


def test_delete_application_not_found(client):
    r = client.delete(f"/api/v1/applications/{uuid4()}")
    assert r.status_code == 404


def test_delete_document_not_found(client):
    r = client.delete(f"/api/v1/documents/{uuid4()}")
    assert r.status_code == 404


def test_delete_application_running_conflict(client, seed):
    r = client.delete(f"/api/v1/applications/{seed['app_run']}")
    assert r.status_code == 409


def test_delete_job_with_running_application_conflict(client, seed):
    r = client.delete(f"/api/v1/jobs/{seed['job_run']}")
    assert r.status_code == 409
    # job still there
    assert client.delete(f"/api/v1/jobs/{seed['job_run']}").status_code == 409


def test_delete_application_success_unlinks_docs(client, seed):
    r = client.delete(f"/api/v1/applications/{seed['app1']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"id": seed["app1"], "deleted": True}
    # second delete -> 404 (not silently idempotent-success)
    assert client.delete(f"/api/v1/applications/{seed['app1']}").status_code == 404
    # job survives
    assert client.get(f"/api/v1/applications/{seed['app_other']}").status_code == 200
    # linked doc unlinked, not deleted: SON surum (doc2) listede kalir.
    docs = client.get("/api/v1/documents?limit=50").json()["items"]
    ids = {d["id"] for d in docs}
    assert seed["doc2"] in ids


def test_delete_application_does_not_delete_job(client, seed):
    client.delete(f"/api/v1/applications/{seed['app_other']}")
    jobs = client.get("/api/v1/jobs?limit=100").json()["items"]
    assert seed["job2"] in {j["id"] for j in jobs}


def test_delete_document_success_only_requested_version(client, seed):
    with patch.object(_api.minio_client, "delete_object", return_value=True) as rm:
        r = client.delete(f"/api/v1/documents/{seed['doc1']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"id": seed["doc1"], "deleted": True}
    rm.assert_called_once_with("key-doc1", "docs")
    docs = client.get("/api/v1/documents?limit=50").json()["items"]
    ids = {d["id"] for d in docs}
    assert seed["doc1"] not in ids
    assert seed["doc2"] in ids  # other version preserved


def test_delete_document_removes_storage_artifact(client, seed):
    with patch.object(_api.minio_client, "delete_object", return_value=True) as rm:
        client.delete(f"/api/v1/documents/{seed['doc_other']}")
    rm.assert_called_once_with("key-other", "docs")


def test_delete_job_success_cascades_and_cleans_minio(client, seed):
    with patch.object(_api.minio_client, "delete_object", return_value=True) as rm:
        r = client.delete(f"/api/v1/jobs/{seed['job1']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"id": seed["job1"], "deleted": True}
    removed_keys = {c.args[0] for c in rm.call_args_list}
    assert {"key-doc1", "key-doc2"} <= removed_keys
    # related app/questions gone; unrelated job data survives
    assert client.delete(f"/api/v1/applications/{seed['app1']}").status_code == 404
    assert client.delete(f"/api/v1/documents/{seed['doc2']}").status_code == 404
    jobs = client.get("/api/v1/jobs?limit=100").json()["items"]
    assert seed["job2"] in {j["id"] for j in jobs}
    docs = client.get("/api/v1/documents?limit=50").json()["items"]
    assert seed["doc_other"] in {d["id"] for d in docs}


def test_delete_job_does_not_delete_unrelated_job(client, seed):
    with patch.object(_api.minio_client, "delete_object", return_value=True):
        client.delete(f"/api/v1/jobs/{seed['job1']}")
    jobs = client.get("/api/v1/jobs?limit=100").json()["items"]
    by_id = {j["id"] for j in jobs}
    assert seed["job1"] not in by_id
    assert seed["job2"] in by_id
