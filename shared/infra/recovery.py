"""Redis Streams pending-message recovery (T5).

A worker that crashes after XREADGROUP but before XACK leaves messages in
the group's Pending Entries List (PEL). Those messages are never delivered
again via `XREADGROUP ... ">"` (new-only). This module reclaims them with
XAUTOCLAIM and routes poison messages to a DLQ stream after MAX_DELIVERIES.

Replay is safe: every stage is idempotent (DB constraints + state checks,
orchestrator skips already-recorded event_ids, cv-generator upserts by
(job_id, type, language, version)).

Spec location per yama.md is `shared/bus/recovery.py`; the canonical module
in this repo is `shared/infra/recovery.py` (bus lives in shared.infra).
"""
import logging
from typing import Any, AsyncGenerator, Dict, Tuple

logger = logging.getLogger(__name__)

MAX_DELIVERIES = 5


async def _delivery_count(redis: Any, stream: str, group: str, msg_id: str) -> int:
    """Returns PEL delivery count for a single message (best-effort)."""
    try:
        pending = await redis.xpending_range(
            stream, group, min=msg_id, max=msg_id, count=1
        )
    except Exception as exc:
        logger.debug("xpending_range failed for %s: %s", msg_id, exc)
        return 1
    if not pending:
        return 1
    entry = pending[0]
    if isinstance(entry, dict):
        for key in ("times_delivered", "deliveries", "times-delivered", "delivery_count"):
            if key in entry:
                try:
                    return int(entry[key])
                except (TypeError, ValueError):
                    pass  # try the next known key name
            return 1
    try:
        # XPENDING range tuple: (id, consumer, idle_ms, deliveries)
        return int(entry[3])
    except (IndexError, TypeError, ValueError):
        return 1


def _split_autoclaim(result: Any) -> Tuple[str, list[Any]]:
    """Normalizes XAUTOCLAIM return shape across redis-py versions."""
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        return str(result[0]), list(result[1] or [])
    return "0-0", []


async def reclaim_stuck(
    redis: Any,
    stream: str,
    group: str,
    consumer: str,
    min_idle_ms: int = 120_000,
    count: int = 50,
) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
    """Yields (msg_id, fields) for idle pending messages; DLQs poison ones.

    Messages delivered >= MAX_DELIVERIES are moved to `{stream}.dlq` with
    `reason=max_deliveries` and ACKed; they are NOT yielded.
    """
    cursor: Any = "0-0"
    while True:
        try:
            result = await redis.xautoclaim(
                stream,
                group,
                consumer,
                min_idle_time=min_idle_ms,
                start_id=cursor,
                count=count,
            )
        except Exception as exc:
            logger.warning("xautoclaim failed on %s/%s: %s", stream, group, exc)
            return
        cursor, msgs = _split_autoclaim(result)
        for item in msgs or []:
            try:
                msg_id, fields = item[0], dict(item[1])
            except (IndexError, TypeError, ValueError):
                continue
            deliveries = await _delivery_count(redis, stream, group, str(msg_id))
            if deliveries >= MAX_DELIVERIES:
                dlq_fields = {**fields, "reason": "max_deliveries", "original_id": str(msg_id)}
                try:
                    await redis.xadd(f"{stream}.dlq", dlq_fields)
                    await redis.xack(stream, group, str(msg_id))
                    logger.warning(
                        "routed poison message %s to %s.dlq after %d deliveries",
                        msg_id,
                        stream,
                        deliveries,
                    )
                except Exception as exc:
                    logger.warning("DLQ routing failed for %s: %s", msg_id, exc)
                continue
            yield str(msg_id), fields
        if str(cursor) == "0-0":
            break
