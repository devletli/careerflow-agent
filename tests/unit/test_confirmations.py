"""B2: Redis destekli tek kullanimlik token testleri (sahte Redis, ag yok).

Gercek atomiklik uretimde Redis GETDEL ile saglanir; buradaki FakeRedis
getdel/set islemlerini await icermeyen senkron dict islemleriyle yapar,
boylece asyncio yarisi da ayni tek-kullanim davranisini dogrular.
"""
import asyncio
import logging
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))

from app import confirmations as conf  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def set(self, key, value, ex=None):
        self.d[key] = (value, (time.monotonic() + ex) if ex else None)

    async def getdel(self, key):
        found = self.d.pop(key, None)
        if found is None:
            return None
        value, deadline = found
        if deadline is not None and deadline <= time.monotonic():
            return None
        return value


@pytest.fixture()
def store():
    return FakeRedis()


async def test_mint_and_consume_once(store):
    token, ttl = await conf.mint_confirmation_token(store, "fill_applications")
    assert ttl == conf.TOKEN_TTL_SECONDS
    assert await conf.consume_confirmation_token(store, token, "fill_applications") is True
    assert await conf.consume_confirmation_token(store, token, "fill_applications") is False


async def test_token_single_use_under_concurrency(store):
    token, _ = await conf.mint_confirmation_token(store, "submit", "app-1")
    results = await asyncio.gather(
        *[conf.consume_confirmation_token(store, token, "submit", "app-1") for _ in range(20)]
    )
    assert results.count(True) == 1


async def test_unknown_token_rejected(store):
    assert await conf.consume_confirmation_token(store, "nope", "fill_applications") is False
    assert await conf.consume_confirmation_token(store, None, "fill_applications") is False
    assert await conf.consume_confirmation_token(store, "", "submit", "app-1") is False


async def test_token_bound_to_action(store):
    token, _ = await conf.mint_confirmation_token(store, "fill_applications")
    assert await conf.consume_confirmation_token(store, token, "submit_application", None) is False


async def test_token_bound_to_application(store):
    token, _ = await conf.mint_confirmation_token(store, "submit", "app-1")
    # GETDEL anlami: yanlis baglama da token'i yakar (fail-closed).
    assert await conf.consume_confirmation_token(store, token, "submit", "app-2") is False
    assert await conf.consume_confirmation_token(store, token, "submit", "app-1") is False


async def test_expired_token_rejected(store):
    token, _ = await conf.mint_confirmation_token(store, "submit", "app-1")
    for key in list(store.d):
        value, _ = store.d[key]
        store.d[key] = (value, 0.0)
    assert await conf.consume_confirmation_token(store, token, "submit", "app-1") is False


async def test_unconfirmable_action_raises(store):
    with pytest.raises(ValueError):
        await conf.mint_confirmation_token(store, "discover")
    with pytest.raises(ValueError):
        await conf.mint_confirmation_token(store, "explode")


async def test_token_never_stored_or_logged_plaintext(store, caplog):
    token, _ = await conf.mint_confirmation_token(store, "submit", "app-1")
    with caplog.at_level(logging.INFO, logger="api"):
        assert await conf.consume_confirmation_token(store, token, "submit", "app-1") is True
    assert token not in caplog.text
    stored_keys = list(store.d.keys())
    assert stored_keys == []  # tuketildi
    token2, _ = await conf.mint_confirmation_token(store, "submit", "app-1")
    assert all(token2 not in key for key in store.d.keys())  # anahtar sha256
