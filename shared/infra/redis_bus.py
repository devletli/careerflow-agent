import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, cast
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from shared.config import settings
from shared.contracts.events import BaseEvent, parse_event

logger = logging.getLogger(__name__)


def calculate_backoff(
    retry_count: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    factor: float = 2.0,
) -> float:
    """Calculates bounded exponential backoff delay in seconds."""
    delay = base_delay * (factor ** retry_count)
    return min(delay, max_delay)


class RedisEventBus:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[aioredis.Redis] = None

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                # socket_timeout must stay comfortably above the largest block_ms used by
                # any consumer (see read_events) to avoid the client raising a socket-level
                # TimeoutError while a blocking XREADGROUP call is legitimately waiting.
                socket_timeout=15.0,
            )
        return self._redis

    async def close(self):
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def ping(self) -> bool:
        try:
            r = await self.get_redis()
            return await r.ping()
        except Exception as e:
            logger.warning(f"Redis ping failed: {e}")
            return False

    async def publish(self, event: BaseEvent, stream: Optional[str] = None) -> str:
        """Publishes an event to a Redis Stream."""
        stream_name = stream or settings.STREAM_EVENTS
        r = await self.get_redis()
        payload_data: Dict[str, Any] = {"data": event.to_json(), "event_type": event.event_type}
        message_id = cast(str, await r.xadd(stream_name, payload_data))  # type: ignore[arg-type]
        logger.debug(f"Published event {event.event_type} ({event.event_id}) to {stream_name}: {message_id}")
        return message_id

    async def ensure_consumer_group(self, stream: str, group: str):
        """Ensures a consumer group exists for a stream."""
        r = await self.get_redis()
        try:
            await r.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info(f"Created consumer group '{group}' on stream '{stream}'")
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, this is expected
                pass
            else:
                raise

    async def read_events(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> List[Tuple[str, BaseEvent]]:
        """
        Reads pending or new messages for the consumer group.
        Returns list of (message_id, event).
        """
        r = await self.get_redis()
        await self.ensure_consumer_group(stream, group)

        messages = await r.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )

        results: List[Tuple[str, BaseEvent]] = []
        if not messages:
            return results

        for entry in messages:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            stream_name, msg_list = entry
            if not isinstance(msg_list, (list, tuple)):
                continue
            for item in msg_list:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                message_id, fields = item
                if not isinstance(fields, dict):
                    continue
                raw_json = fields.get("data")
                if raw_json:
                    try:
                        event = parse_event(raw_json)
                        results.append((str(message_id), event))
                    except Exception as ex:
                        logger.error(f"Failed to parse event from stream {stream_name} id {message_id}: {ex}")
        return results

    async def ack(self, stream: str, group: str, message_id: str) -> int:
        """Acknowledges a message in the consumer group."""
        r = await self.get_redis()
        return await r.xack(stream, group, message_id)

    async def reclaim_events(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int = 120_000,
        count: int = 50,
    ) -> List[Tuple[str, BaseEvent]]:
        """Reclaims idle pending messages (T5) and parses them as events.

        Poison messages (>= MAX_DELIVERIES) are DLQ-routed inside
        shared.infra.recovery and never returned. Call this at the top of
        each worker loop before read_events() so crashed-worker messages
        are reprocessed (idempotently) instead of stuck in the PEL.
        """
        from shared.infra.recovery import reclaim_stuck

        r = await self.get_redis()
        await self.ensure_consumer_group(stream, group)
        results: List[Tuple[str, BaseEvent]] = []
        async for message_id, fields in reclaim_stuck(
            r, stream, group, consumer, min_idle_ms=min_idle_ms, count=count
        ):
            raw_json = fields.get("data")
            if not raw_json:
                continue
            try:
                results.append((message_id, parse_event(raw_json)))
            except Exception as ex:
                logger.error(f"Failed to parse reclaimed event {message_id}: {ex}")
        return results

    @asynccontextmanager
    async def acquire_lock(
        self,
        lock_name: str,
        timeout: float = 30.0,
        blocking_timeout: float = 5.0,
    ) -> AsyncGenerator[bool, None]:
        """
        Distributed lock context manager using Redis.
        Yields True if lock acquired, False otherwise.
        """
        r = await self.get_redis()
        lock = r.lock(
            f"lock:{lock_name}",
            timeout=timeout,
            blocking_timeout=blocking_timeout,
        )
        acquired = await lock.acquire()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    await lock.release()
                except Exception as ex:
                    logger.debug(f"Error releasing lock {lock_name}: {ex}")

    async def publish_dead_letter(
        self,
        original_event: BaseEvent,
        error_message: str,
        stack_trace: Optional[str] = None,
        retry_count: int = 0,
    ) -> str:
        """Pushes an unprocessable or exhausted event to the dead-letter stream."""
        r = await self.get_redis()
        dlq_data: Dict[str, Any] = {
            "original_event_id": original_event.event_id,
            "event_type": original_event.event_type,
            "data": original_event.to_json(),
            "error_message": error_message,
            "stack_trace": stack_trace or "",
            "retry_count": str(retry_count),
        }
        message_id = cast(str, await r.xadd(settings.STREAM_DEAD_LETTER, dlq_data))  # type: ignore[arg-type]
        logger.warning(
            f"Event {original_event.event_id} ({original_event.event_type}) routed to dead letter stream: {message_id}"
        )
        return message_id
