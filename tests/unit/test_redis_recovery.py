"""T5 Redis Streams pending-recovery tests (offline, mocked redis).

- crashed worker (read but never ACKed) message is reclaimed and reprocessed
- poison message (>= MAX_DELIVERIES) goes to DLQ and is never yielded
- replay stays idempotent: same msg_id returned once per reclaim sweep
- multi-batch cursor loop drains all stuck messages
"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from shared.contracts.events import JobDiscoveredEvent
from shared.infra.recovery import MAX_DELIVERIES, reclaim_stuck


def _event_fields(**extra):
    ev = JobDiscoveredEvent(
        correlation_id="corr-1",
        entity_id=str(uuid4()),
        payload={"company": "TestCorp"},
    )
    return {"data": ev.to_json(), "event_type": ev.event_type, **extra}


def _mock_redis(batches, deliveries=1):
    """batches: list of [(msg_id, fields)] per xautoclaim call."""
    redis = AsyncMock()
    calls = {"n": 0}

    async def _autoclaim(*args, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        if idx < len(batches):
            # last batch closes the cursor; earlier ones paginate
            cursor = "0-0" if idx == len(batches) - 1 else f"cursor-{idx + 1}"
            return [cursor, batches[idx]]
        return ["0-0", []]

    async def _pending_range(stream, group, min=None, max=None, count=1, **kw):
        return [("x", "c", 1000, deliveries)]

    redis.xautoclaim = AsyncMock(side_effect=_autoclaim)
    redis.xpending_range = AsyncMock(side_effect=_pending_range)
    redis.xadd = AsyncMock(return_value="dlq-1")
    redis.xack = AsyncMock(return_value=1)
    return redis


@pytest.mark.asyncio
async def test_crashed_worker_message_is_reclaimed():
    redis = _mock_redis([[("1700000000000-0", _event_fields())]])
    out = [item async for item in reclaim_stuck(redis, "s", "g", "c", min_idle_ms=1)]
    assert len(out) == 1
    assert out[0][0] == "1700000000000-0"
    assert redis.xack.call_count == 0  # healthy message stays pending for caller to ACK


@pytest.mark.asyncio
async def test_poison_message_goes_to_dlq_and_is_skipped():
    redis = _mock_redis(
        [[("1700000000000-9", _event_fields())]],
        deliveries=MAX_DELIVERIES,
    )
    out = [item async for item in reclaim_stuck(redis, "s", "g", "c", min_idle_ms=1)]
    assert out == []
    redis.xadd.assert_called_once()
    args, _ = redis.xadd.call_args
    assert args[0] == "s.dlq"
    assert args[1]["reason"] == "max_deliveries"
    redis.xack.assert_called_once_with("s", "g", "1700000000000-9")


@pytest.mark.asyncio
async def test_mixed_batch_healthy_yielded_poison_dlqed():
    redis = AsyncMock()
    healthy = ("1700000000000-0", _event_fields())
    poison = ("1700000000000-1", _event_fields())

    async def _autoclaim(*args, **kwargs):
        return ["0-0", [healthy, poison]]

    async def _pending_range(stream, group, min=None, max=None, count=1, **kw):
        return [("x", "c", 1, MAX_DELIVERIES if max == "1700000000000-1" else 1)]

    redis.xautoclaim = AsyncMock(side_effect=_autoclaim)
    redis.xpending_range = AsyncMock(side_effect=_pending_range)
    redis.xadd = AsyncMock(return_value="dlq-1")
    redis.xack = AsyncMock(return_value=1)

    out = [item async for item in reclaim_stuck(redis, "s", "g", "c", min_idle_ms=1)]
    assert [m for m, _ in out] == ["1700000000000-0"]
    redis.xadd.assert_called_once()
    redis.xack.assert_called_once_with("s", "g", "1700000000000-1")


@pytest.mark.asyncio
async def test_cursor_pagination_drains_all_batches():
    redis = _mock_redis(
        [
            [("1700000000000-0", _event_fields())],
            [("1700000000000-1", _event_fields())],
        ]
    )
    out = [item async for item in reclaim_stuck(redis, "s", "g", "c", min_idle_ms=1)]
    assert [m for m, _ in out] == ["1700000000000-0", "1700000000000-1"]
    assert redis.xautoclaim.call_count == 2


@pytest.mark.asyncio
async def test_bus_reclaim_events_parses_and_skips_poison():
    from shared.infra.redis_bus import RedisEventBus

    bus = RedisEventBus()
    redis = AsyncMock()
    good = ("1700000000000-0", _event_fields())
    bad = ("1700000000000-1", {"data": "not-json{{{", "event_type": "job.discovered.v1"})

    async def _autoclaim(*args, **kwargs):
        return ["0-0", [good, bad]]

    redis.xautoclaim = AsyncMock(side_effect=_autoclaim)
    redis.xpending_range = AsyncMock(return_value=[("x", "c", 1, 1)])
    redis.xgroup_create = AsyncMock()
    bus._redis = redis

    events = await bus.reclaim_events("s", "g", "c", min_idle_ms=1)
    assert len(events) == 1
    assert events[0][0] == "1700000000000-0"
    assert events[0][1].event_type == "job.discovered.v1"


def test_workers_call_reclaim_before_read():
    """All 6 workers must reclaim pending messages before reading new ones."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    workers = [
        "services/orchestrator/app/worker.py",
        "services/job-discovery/app/worker.py",
        "services/job-matching/app/worker.py",
        "services/cv-generator/app/worker.py",
        "services/application-analyzer/app/worker.py",
        "services/browser-agent/app/worker.py",
    ]
    for rel in workers:
        src = (root / rel).read_text(encoding="utf-8")
        assert "reclaim_events" in src, f"{rel} must call reclaim_events (T5)"
        assert src.index("reclaim_events") < src.index("read_events"), f"{rel}: reclaim first"
