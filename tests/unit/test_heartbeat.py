"""Gorev 7: worker heartbeat (sahte redis, ag yok)."""
from unittest.mock import AsyncMock

from shared.infra.heartbeat import HB_TTL_SECONDS, beat


async def test_beat_sets_ttl_key():
    r = AsyncMock()
    await beat(r, "job-matching")
    r.set.assert_awaited_once()
    args, kwargs = r.set.await_args
    assert args[0] == "hb:job-matching"
    assert kwargs.get("ex") == HB_TTL_SECONDS


async def test_beat_custom_service_and_ttl():
    r = AsyncMock()
    await beat(r, "browser-agent", ttl=10)
    args, kwargs = r.set.await_args
    assert args[0] == "hb:browser-agent"
    assert kwargs.get("ex") == 10


def test_all_workers_wire_heartbeat():
    """Her worker beat()'i hem import etmeli hem cagirmali (NameError yakalama)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "services"
    workers = [
        "orchestrator",
        "job-discovery",
        "job-matching",
        "cv-generator",
        "application-analyzer",
        "browser-agent",
    ]
    for name in workers:
        src = (root / name / "app" / "worker.py").read_text(encoding="utf-8")
        assert "from shared.infra.heartbeat import beat" in src, name
        assert "await beat(" in src, name
