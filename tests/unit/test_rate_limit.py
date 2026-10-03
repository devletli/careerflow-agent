"""Faz 5-D: Redis fixed-window rate limiter unit tests (fake redis, no I/O)."""
import pytest

from shared.infra.rate_limit import ACTION_LIMITS, RateLimited, check_action_limit


class _FakePipeline:
    def __init__(self, store):
        self._store = store
        self._ops = []

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "incr":
                self._store[op[1]] = self._store.get(op[1], 0) + 1
                results.append(self._store[op[1]])
            else:
                results.append(True)
        return results


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return _FakePipeline(self.store)


@pytest.mark.asyncio
async def test_allows_up_to_limit_then_raises(monkeypatch):
    import shared.infra.rate_limit as rl

    monkeypatch.setitem(rl.ACTION_LIMITS, "discover", (2, 3600))
    redis = _FakeRedis()
    await check_action_limit("discover", redis)
    await check_action_limit("discover", redis)
    with pytest.raises(RateLimited) as exc_info:
        await check_action_limit("discover", redis)
    assert exc_info.value.retry_after_seconds == 3600


@pytest.mark.asyncio
async def test_unknown_actions_unlimited():
    await check_action_limit("match", _FakeRedis())


@pytest.mark.asyncio
async def test_redis_failure_fails_open(monkeypatch):
    class _Broken:
        def pipeline(self):
            raise ConnectionError("redis down")

    await check_action_limit("discover", _Broken())  # must not raise


def test_action_limits_defined_for_control_plane():
    assert set(ACTION_LIMITS) >= {"discover", "fill_applications", "submit_application"}
