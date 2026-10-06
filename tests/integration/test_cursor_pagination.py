"""F1: applications/documents cursor sayfalama testleri (SQLite, offline).

- Varsayılan sıra: REQUIRES_HUMAN/FAILED/BLOCKED önce, sonra
  READY_TO_SUBMIT, CREATED, RUNNING, SUBMITTED; grup içinde skor DESC,
  updated_at DESC, id ASC.
- Stabil cursor: aynı skor + aynı updated_at ile 120 satır, sayfa sayfa
  gezince kopya/atlama yok.
- limit üst sınırı (51) ve bozuk cursor 422.
- Documents: (application-or-job, tür, dil) başına SON sürüm; dil
  partition'a dahil (TR ve EN CV aynı anda yaşar); cursor (created_at, id).
- q içindeki % ve _ kaçırılır (joker gibi davranmaz).
"""
import importlib.util
import sys
from datetime import datetime, timezone
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
    spec = importlib.util.spec_from_file_location("careerflow_api_cursors", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_cursors"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import Application, Base, Document, Job, JobMatch  # noqa: E402

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
        job = Job(
            id=uuid4(), source="manual", source_job_id="cur-1", company="Acme",
            title="DevOps Engineer", url="https://acme.example/j/1",
            job_fingerprint="fp-cur-1", status="NORMALIZED",
        )
        s.add(job)
        await s.flush()
        # Sıra testi: her durumdan birer satır, skorlar karışık.
        specs = [
            ("SUBMITTED", 99.0),
            ("RUNNING", 10.0),
            ("CREATED", 50.0),
            ("READY_TO_SUBMIT", 70.0),
            ("BLOCKED", 5.0),
            ("FAILED", 60.0),
            ("REQUIRES_HUMAN", 40.0),
        ]
        for i, (st, score) in enumerate(specs):
            j = Job(
                id=uuid4(), source="manual", source_job_id=f"ord-{i}", company=f"C{i}",
                title=f"Role {i}", url=f"https://example.example/j/ord-{i}",
                job_fingerprint=f"fp-ord-{i}", status="NORMALIZED",
            )
            s.add(j)
            await s.flush()
            s.add(JobMatch(
                id=uuid4(), job_id=j.id, overall_score=score, confidence=0.9,
                qualification_status="QUALIFIED",
            ))
            s.add(Application(
                id=uuid4(), job_id=j.id, candidate_id="cand-1",
                application_fingerprint=f"fp-app-ord-{i}", status=st,
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
        # Stabilite testi: 120 satır, aynı skor + aynı updated_at.
        same_ts = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(120):
            j = Job(
                id=uuid4(), source="manual", source_job_id=f"st-{i}", company="Same",
                title=f"Same Role {i}", url=f"https://example.example/j/st-{i}",
                job_fingerprint=f"fp-st-{i}", status="NORMALIZED",
            )
            s.add(j)
            await s.flush()
            s.add(JobMatch(
                id=uuid4(), job_id=j.id, overall_score=77.0, confidence=0.9,
                qualification_status="QUALIFIED",
            ))
            s.add(Application(
                id=uuid4(), job_id=j.id, candidate_id="cand-1",
                application_fingerprint=f"fp-app-st-{i}", status="CREATED",
                updated_at=same_ts,
            ))
        # q kaçış testi: adında % ve _ olan şirket.
        esc_job = Job(
            id=uuid4(), source="manual", source_job_id="esc-1", company="100%_Sure",
            title="QA", url="https://example.example/j/esc-1",
            job_fingerprint="fp-esc-1", status="NORMALIZED",
        )
        s.add(esc_job)
        await s.flush()
        s.add(Application(
            id=uuid4(), job_id=esc_job.id, candidate_id="cand-1",
            application_fingerprint="fp-app-esc-1", status="CREATED",
        ))
        # Documents: aynı iş için cv TR v1+v2, cv EN v1, cover_letter TR v1.
        for typ, lang, ver in [("cv", "tr", 1), ("cv", "tr", 2), ("cv", "en", 1), ("cover_letter", "tr", 1)]:
            s.add(Document(
                id=uuid4(), job_id=job.id, type=typ, language=lang, version=ver,
                minio_bucket="b", minio_key=f"k-{typ}-{lang}-{ver}",
                content_hash=f"h-{typ}-{lang}-{ver}",
                created_at=datetime(2026, 3, ver, tzinfo=timezone.utc),
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


def test_applications_default_order_and_counts(client, seed):
    body = client.get("/api/v1/applications", params={"limit": 50}).json()
    assert set(body) >= {"items", "next_cursor", "total", "status_counts"}
    first = [a["status"] for a in body["items"][:7]]
    # "Seni bekleyenler" grubu (REQUIRES_HUMAN/FAILED/BLOCKED) en üstte.
    assert set(first[:3]) == {"REQUIRES_HUMAN", "FAILED", "BLOCKED"}
    assert first[3] == "READY_TO_SUBMIT"
    assert body["status_counts"]["CREATED"] >= 121
    assert body["status_counts"]["BLOCKED"] == 1


def test_applications_stable_cursor_no_dup_no_skip(client, seed):
    seen = []
    cursor = None
    for _ in range(10):
        params = {"limit": 50, "status": "CREATED"}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/v1/applications", params=params).json()
        seen.extend(a["id"] for a in body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    # 1 sıra-satırı (CREATED 50.0) + 120 stabilite-satırı + 1 kaçış-satırı.
    assert len(seen) == 122
    assert len(set(seen)) == 122


def test_applications_limit_and_bad_cursor_422(client, seed):
    assert client.get("/api/v1/applications", params={"limit": 51}).status_code == 422
    assert client.get("/api/v1/applications", params={"cursor": "bozuk"}).status_code == 422
    assert client.get("/api/v1/applications", params={"cursor": "e30="}).status_code == 422


def test_documents_latest_per_type_language(client, seed):
    body = client.get("/api/v1/documents").json()
    assert set(body) >= {"items", "next_cursor", "total"}
    # 4 satırdan yalnızca 3 son sürüm: cv/tr v2, cv/en v1, cover_letter/tr v1.
    assert body["total"] == 3
    versions = {(d["type"], d["language"]): d["version"] for d in body["items"]}
    assert versions == {("cv", "tr"): 2, ("cv", "en"): 1, ("cover_letter", "tr"): 1}
    # Dil rozeti için language alanı dolu gelir.
    assert {d["language"] for d in body["items"]} == {"tr", "en"}


def test_documents_cursor_and_limits(client, seed):
    assert client.get("/api/v1/documents", params={"limit": 51}).status_code == 422
    assert client.get("/api/v1/documents", params={"cursor": "bozuk"}).status_code == 422
    first = client.get("/api/v1/documents", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]
    second = client.get(
        "/api/v1/documents", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    ids = [d["id"] for d in first["items"]] + [d["id"] for d in second["items"]]
    assert len(set(ids)) == 3


def test_q_escapes_percent_underscore(client, seed):
    # "%" tek başına joker gibi davranırsa 100%-eşleşme dönerdi; tam ad aranır.
    body = client.get("/api/v1/applications", params={"q": "100%_Sure"}).json()
    assert body["total"] == 1
    body = client.get("/api/v1/documents", params={"q": "100%_Sure"}).json()
    assert body["total"] == 0  # kaçış-satırının belgesi yok; ama 422 de yok
    assert client.get("/api/v1/documents", params={"q": "100%"}).json()["total"] == 0
