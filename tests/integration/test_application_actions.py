"""yama.md P0 regression tests: explicit per-application execute actions.

Covers the /execute contract end to end (offline, SQLite + mocked redis):
- prepare: CREATED -> READY_TO_SUBMIT (idempotent from ready, 409 otherwise)
- submit: READY_* -> 202 queued; SUBMITTED / REQUIRES_HUMAN rejected
- retry: only FAILED may retry (safe default retryable=false elsewhere)
- continue: only REQUIRES_HUMAN, returns an honest manual workflow
- unknown actions rejected with 422
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))


def _load_api():
    path = ROOT / "services" / "api" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("careerflow_api_actions", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_api_actions"] = module
    spec.loader.exec_module(module)
    return module


_api = _load_api()

from app.security import require_api_key  # noqa: E402
from shared.db.models import Application, Base, Job  # noqa: E402

_api.app.dependency_overrides[require_api_key] = lambda: None


def _make_app(session, job_id, status, **kwargs):
    app = Application(
        id=uuid4(),
        job_id=job_id,
        candidate_id="cand-1",
        application_fingerprint=f"fp-{uuid4().hex}",
        status=status,
        **kwargs,
    )
    session.add(app)
    return app


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
            id=uuid4(), source="manual", source_job_id="act-1", company="Acme",
            title="DevOps Engineer", url="https://acme.example/j/1",
            application_url="https://acme.example/j/1/apply",
            job_fingerprint="fp-act-1", status="NORMALIZED",
        )
        s.add(job)
        await s.flush()
        ids = {"job": job.id}
        ids["created"] = _make_app(s, job.id, "CREATED").id
        ids["ready"] = _make_app(s, job.id, "READY_TO_SUBMIT").id
        ids["submitted"] = _make_app(s, job.id, "SUBMITTED").id
        ids["failed"] = _make_app(
            s, job.id, "FAILED", failure_reason="Form timeout before submit"
        ).id
        ids["human"] = _make_app(
            s, job.id, "REQUIRES_HUMAN",
            blocked_reason="Submission result could not be verified",
        ).id
        ids["running"] = _make_app(s, job.id, "RUNNING").id
        ids["blocked"] = _make_app(
            s, job.id, "BLOCKED", blocked_reason="CAPTCHA detected"
        ).id
        await s.commit()
        ids = {k: (str(v) if not isinstance(v, str) else v) for k, v in ids.items()}
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


def _execute(client, app_id, action, token=None):
    body = {"action": action}
    if token is not None:
        body["confirmation_token"] = token
    return client.patch(f"/api/v1/applications/{app_id}/execute", json=body)


def _mint(client, action, application_id=None):
    body = {"action": action}
    if application_id is not None:
        body["application_id"] = application_id
    r = client.post("/api/v1/confirmations", json=body)
    assert r.status_code == 200, r.text
    return r.json()["confirmation_token"]


def test_prepare_transitions_created_to_ready(client, seed):
    r = _execute(client, seed["created"], "prepare")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "READY_TO_SUBMIT"


def test_prepare_idempotent_from_ready(client, seed):
    r = _execute(client, seed["ready"], "prepare")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "READY_TO_SUBMIT"


def test_prepare_rejected_from_submitted(client, seed):
    assert _execute(client, seed["submitted"], "prepare").status_code == 409


def test_submit_queues_from_ready(client, seed, monkeypatch):
    from shared.config import settings

    monkeypatch.setattr(settings, "AUTOMATION_MODE", "FULL_AUTO")
    monkeypatch.setattr(settings, "AUTO_SUBMIT", True)
    with patch.object(
        _api.redis_bus, "publish", new=AsyncMock(return_value="msg-1")
    ) as publish:
        token = _mint(client, "submit", seed["ready"])
        r = _execute(client, seed["ready"], "submit", token=token)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["action"] == "submit"
    assert body["application_id"] == seed["ready"]
    publish.assert_awaited_once()
    event = publish.await_args.args[0]
    assert event.payload["action"] == "submit_application"
    assert event.payload["application_id"] == seed["ready"]


def test_submit_rejected_when_mode_disables(client, seed):
    # Default test settings are PREPARE_APPLICATION / AUTO_SUBMIT=false:
    # submit must be rejected with an actionable message instead of
    # silently filling (which could never yield SUBMITTED/REQUIRES_HUMAN).
    # Faz 3B: UI onayina guvenilmez; once token sart.
    r = _execute(client, seed["ready"], "submit")
    assert r.status_code == 409
    assert "confirmation token" in r.json()["detail"]
    token = _mint(client, "submit", seed["ready"])
    r = _execute(client, seed["ready"], "submit", token=token)
    assert r.status_code == 409
    assert "FULL_AUTO" in r.json()["detail"]


def test_submit_rejected_when_already_submitted(client, seed):
    assert _execute(client, seed["submitted"], "submit").status_code == 409


def test_submit_rejected_when_uncertain(client, seed):
    r = _execute(client, seed["human"], "submit")
    assert r.status_code == 409
    assert "retryable=false" in r.json()["detail"]


def test_retry_allowed_only_from_failed(client, seed):
    r = _execute(client, seed["failed"], "retry")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": seed["failed"],
        "status": "READY_TO_SUBMIT",
        "action": "retry",
        "retryable": True,
    }
    assert _execute(client, seed["submitted"], "retry").status_code == 409
    r = _execute(client, seed["human"], "retry")
    assert r.status_code == 409
    assert "retryable=false" in r.json()["detail"]
    assert _execute(client, seed["running"], "retry").status_code == 409
    assert _execute(client, seed["blocked"], "retry").status_code == 409


def test_continue_returns_manual_workflow(client, seed):
    r = _execute(client, seed["human"], "continue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "REQUIRES_HUMAN"  # status untouched: no fake resume
    assert body["application_url"] == "https://acme.example/j/1/apply"
    assert len(body["manual_steps"]) >= 2
    assert _execute(client, seed["created"], "continue").status_code == 409


def test_unknown_action_rejected(client, seed):
    assert _execute(client, seed["ready"], "explode").status_code == 422


def test_missing_application_404(client):
    assert _execute(client, str(uuid4()), "prepare").status_code == 404


def test_manual_rejects_non_public_urls(client):
    for url in (
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1:8000/api/v1/status",
        "http://10.0.0.5/apply",
        "http://169.254.169.254/latest/meta-data/",
    ):
        r = client.post("/api/v1/applications/manual", json={"url": url})
        assert r.status_code == 422, (url, r.text)


def test_pipeline_action_rate_limited(client, seed, monkeypatch):
    from shared.infra.rate_limit import RateLimited

    async def deny(action, redis):
        raise RateLimited(action=action, retry_after_seconds=60)

    monkeypatch.setattr(_api, "check_action_limit", deny)
    r = client.post(
        "/api/v1/pipeline/actions",
        json={"action": "discover", "confirmed": False},
    )
    assert r.status_code == 429, r.text
    assert r.headers.get("Retry-After") == "60"


def test_pipeline_action_allowed_when_limiter_passes(client, seed, monkeypatch):
    async def allow(action, redis):
        return None

    monkeypatch.setattr(_api, "check_action_limit", allow)
    with patch.object(
        _api.redis_bus, "publish", new=AsyncMock(return_value="msg-1")
    ):
        r = client.post(
            "/api/v1/pipeline/actions",
            json={"action": "discover", "confirmed": False},
        )
    assert r.status_code == 202, r.text


def test_confirmations_reject_unknown_action(client, seed):
    r = client.post("/api/v1/confirmations", json={"action": "explode"})
    assert r.status_code == 422


def test_confirmations_require_app_for_submit(client, seed):
    assert client.post("/api/v1/confirmations", json={"action": "submit"}).status_code == 422
    r = client.post(
        "/api/v1/confirmations",
        json={"action": "submit", "application_id": seed["ready"]},
    )
    assert r.status_code == 200
    assert r.json()["expires_in"] == 300


def test_pipeline_fill_requires_single_use_token(client, seed, monkeypatch):
    async def allow(action, redis):
        return None

    monkeypatch.setattr(_api, "check_action_limit", allow)
    with patch.object(
        _api.redis_bus, "publish", new=AsyncMock(return_value="msg-1")
    ):
        base = {"action": "fill_applications", "confirmed": True}
        r = client.post("/api/v1/pipeline/actions", json=base)
        assert r.status_code == 409
        assert "confirmation token" in r.json()["detail"]
        token = _mint(client, "fill_applications")
        r = client.post("/api/v1/pipeline/actions", json={**base, "confirmation_token": token})
        assert r.status_code == 202, r.text
        # Ayni token ikinci kez gecersiz.
        r = client.post("/api/v1/pipeline/actions", json={**base, "confirmation_token": token})
        assert r.status_code == 409


def test_pipeline_token_bound_to_action(client, seed, monkeypatch):
    async def allow(action, redis):
        return None

    monkeypatch.setattr(_api, "check_action_limit", allow)
    token = _mint(client, "fill_applications")
    r = client.post(
        "/api/v1/pipeline/actions",
        json={
            "action": "submit_application",
            "confirmed": True,
            "application_id": seed["ready"],
            "confirmation_token": token,
        },
    )
    assert r.status_code == 409
    assert "confirmation token" in r.json()["detail"]
