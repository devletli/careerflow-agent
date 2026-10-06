"""Faz 6: score-ranked keyset jobs API (offline, SQLite + mocked API key)."""
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))


def _load_api():
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_ranking", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_ranking"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import Base, Job, JobMatch  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


@pytest.fixture()
async def maker():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    mk = async_sessionmaker(bind=engine, expire_on_commit=False)
    from shared.db.session import get_db_session

    async def _override():
        async with mk() as session:
            yield session
            await session.commit()

    _api.app.dependency_overrides[get_db_session] = _override
    yield mk
    _api.app.dependency_overrides.pop(get_db_session, None)
    await engine.dispose()


@pytest.fixture()
def client(maker):
    yield __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(_api.app)


async def seed_jobs(maker, scores, status="NORMALIZED"):
    ids = []
    async with maker() as s:
        for i, score in enumerate(scores):
            job = Job(
                id=uuid4(), source="test", source_job_id=f"seed-{uuid4().hex[:8]}",
                company=f"C{i}", title=f"T{i}", url=f"https://x.example/{i}",
                job_fingerprint=f"fp-{uuid4().hex}", status=status,
            )
            s.add(job)
            await s.flush()
            ids.append(job.id)
            if score is not None:
                s.add(JobMatch(
                    job_id=job.id, overall_score=float(score), confidence=0.9,
                    qualification_status="QUALIFIED" if score >= 90 else "REVIEW",
                ))
        await s.commit()
    return [str(i) for i in ids]


def test_sorted_by_score_desc_unscored_last(client, maker):
    import asyncio

    asyncio.get_event_loop().run_until_complete(seed_jobs(maker, [40, 95, None, 72, 95, 10]))
    r = client.get("/api/v1/jobs?limit=100").json()
    scores = [it["match_score"] for it in r["items"]]
    assert scores == [95, 95, 72, 40, 10, None]
    assert r["total"] == 6 and r["scored"] == 5 and r["unscored"] == 1


def test_keyset_pagination_is_stable_with_ties(client, maker):
    import asyncio

    asyncio.get_event_loop().run_until_complete(seed_jobs(maker, [90] * 250 + [50] * 10))
    seen, cursor = [], None
    while True:
        url = "/api/v1/jobs?limit=100" + (f"&cursor={cursor}" if cursor else "")
        r = client.get(url).json()
        seen += [it["id"] for it in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 260  # kopya/atlama yok


def test_limit_is_capped(client, maker):
    assert client.get("/api/v1/jobs?limit=5000").status_code == 422


def test_stale_hidden_by_default(client, maker):
    import asyncio

    asyncio.get_event_loop().run_until_complete(seed_jobs(maker, [80]))
    asyncio.get_event_loop().run_until_complete(seed_jobs(maker, [99], status="STALE"))
    default_ids = {it["match_score"] for it in client.get("/api/v1/jobs").json()["items"]}
    assert default_ids == {80}
    all_ids = {it["match_score"] for it in client.get("/api/v1/jobs?include_stale=true").json()["items"]}
    assert all_ids == {80, 99}


def _load_matcher():
    import importlib.util

    path = ROOT / "services" / "job-matching" / "app" / "matcher.py"
    spec = importlib.util.spec_from_file_location("careerflow_job_matcher", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_job_matcher"] = module
    spec.loader.exec_module(module)
    return module


def test_llm_budget_never_changes_score():
    _matcher = _load_matcher()
    RunBudget = _matcher.RunBudget
    JobMatchingEngine = _matcher.JobMatchingEngine
    from shared.contracts.models import JobMatchResult, QualificationStatus

    budget = RunBudget(1)
    assert budget.take() is True
    assert budget.take() is False  # tukendi
    assert len(budget) == 0
    # NOT_QUALIFIED skoru tuketmez, aciklama uretmez.
    res = JobMatchResult(
        job_id=uuid4(), overall_score=10.0, confidence=0.5,
        qualification=QualificationStatus.NOT_QUALIFIED, explanation="Overall Match Score: 10%",
    )
    import asyncio

    async def _run():
        engine = JobMatchingEngine()
        fresh = RunBudget(5)
        applied = await engine.explain_if_needed(
            result=res, title="T", description="D",
            profile=type("P", (), {"experience_years": 1, "skills": [], "languages": {},
                                   "preferences": {}})(),
            budget=fresh,
        )
        return applied, len(fresh)

    applied, remaining = asyncio.run(_run())
    assert applied is False and remaining == 5


def test_frontend_jobs_contract():
    src = (ROOT / "services" / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    tab = (ROOT / "services" / "frontend" / "app" / "components" / "tabs" / "JobsTab.js").read_text(encoding="utf-8")
    # Jobs sekmesi limit=100 ister, Sonraki cursor gonderir, polling cursor'i sifirlamaz.
    assert "limit=100" in src and "cursor" in src
    assert "cursorStack" in src and "jobsMetaQ" in src
    assert '"jobs.minScore"' in src and '"jobs.band"' in src and '"jobs.source"' in src
    assert "next_cursor" in src and "recent_days" in src
    assert "hasNext" in tab and "onNext" in tab
    # Ilk sayfada en fazla 100 satir: backend limit + frontend tek sayfa gosterimi.
    assert "limit=100" in tab or "Next 100" in tab or "nextPage" in tab
