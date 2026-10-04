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
