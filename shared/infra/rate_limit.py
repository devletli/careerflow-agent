"""Redis fixed-window rate limiter for control-plane actions (yama.md Faz 5-D).

Scope is deliberately narrow: only the pipeline action trigger endpoint
(discover / fill / submit) is guarded. The per-application daily/hourly
submission limits are separate and untouched.

Design notes:
- No new dependencies: plain INCR + EXPIRE via an atomic pipeline.
- Fail-open on Redis errors (single-user local tool: availability wins over
  strictness); the refusal is logged as a warning.
- `check_action_limit` raises RateLimited with retry_after_seconds so the
  API can answer 429 honestly.
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class _RedisPipeline(Protocol):
    def incr(self, key: str) -> Any: ...
    def expire(self, key: str, seconds: int) -> Any: ...
    async def execute(self) -> list[Any]: ...


@runtime_checkable
class _RedisClient(Protocol):
    def pipeline(self) -> _RedisPipeline: ...

# action -> (max calls, window seconds). Conservative control-plane caps.
ACTION_LIMITS: dict[str, tuple[int, int]] = {
    "discover": (12, 3600),
    "fill_applications": (20, 3600),
    "submit_application": (10, 3600),
}


@dataclass
class RateLimited(Exception):
    action: str
    retry_after_seconds: int


async def check_action_limit(action: str, redis: _RedisClient) -> None:
    """Raises RateLimited when the fixed window for `action` is exhausted."""
    limit_cfg = ACTION_LIMITS.get(action)
    if limit_cfg is None:
        return
    limit, window_s = limit_cfg
    window_id = int(time.time() // window_s)
    key = f"ratelimit:{action}:{window_id}"
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_s)
        results = await pipe.execute()
        count = int(results[0])
    except Exception as exc:
        logger.warning("rate limiter unavailable for %s: %s (fail-open)", action, exc)
        return
    if count > limit:
        raise RateLimited(action=action, retry_after_seconds=window_s)
