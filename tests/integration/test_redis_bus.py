import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from shared.contracts.events import JobDiscoveredEvent
from shared.infra.redis_bus import RedisEventBus


@pytest.mark.asyncio
async def test_redis_event_bus_publish():
    bus = RedisEventBus()
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1600000000000-0")
    bus._redis = mock_redis

    event = JobDiscoveredEvent(
        correlation_id="corr-1",
        entity_id=str(uuid4()),
        payload={"company": "TestCorp", "title": "DevOps Engineer"},
    )

    msg_id = await bus.publish(event, stream="test:stream")
    assert msg_id == "1600000000000-0"
    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "test:stream"
    assert "job.discovered.v1" in call_args[0][1]["data"]


@pytest.mark.asyncio
async def test_redis_event_bus_read_and_parse():
    bus = RedisEventBus()
    mock_redis = AsyncMock()
    event = JobDiscoveredEvent(
        correlation_id="corr-read",
        entity_id="entity-123",
        payload={"company": "ReadCorp"},
    )
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.xreadgroup = AsyncMock(
        return_value=[
            (
                "test:stream",
                [("1600000000000-1", {"data": event.to_json(), "event_type": event.event_type})],
            )
        ]
    )
    bus._redis = mock_redis

    events = await bus.read_events(
        stream="test:stream",
        group="test-group",
        consumer="test-consumer",
    )
    assert len(events) == 1
    msg_id, received_event = events[0]
    assert msg_id == "1600000000000-1"
    assert isinstance(received_event, JobDiscoveredEvent)
    assert received_event.correlation_id == "corr-read"


@pytest.mark.asyncio
async def test_redis_event_bus_ack():
    bus = RedisEventBus()
    mock_redis = AsyncMock()
    mock_redis.xack = AsyncMock(return_value=1)
    bus._redis = mock_redis

    acked = await bus.ack("test:stream", "test-group", "1600000000000-1")
    assert acked == 1
    mock_redis.xack.assert_called_once_with("test:stream", "test-group", "1600000000000-1")


@pytest.mark.asyncio
async def test_redis_dead_letter_publish():
    bus = RedisEventBus()
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1600000000000-2")
    bus._redis = mock_redis

    event = JobDiscoveredEvent(
        correlation_id="corr-dlq",
        entity_id="entity-dlq",
        payload={"company": "FailCorp"},
    )

    msg_id = await bus.publish_dead_letter(
        original_event=event,
        error_message="Test failure",
        stack_trace="Traceback...",
        retry_count=3,
    )
    assert msg_id == "1600000000000-2"
    mock_redis.xadd.assert_called_once()
