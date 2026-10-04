"""Faz 3B: tek kullanimlik onay tokeni unit testleri (ag/yok, DB yok)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "api"))

from app import confirmations as conf  # noqa: E402


def test_mint_and_consume_once():
    token, ttl = conf.mint_confirmation_token("fill_applications")
    assert ttl == conf.TOKEN_TTL_SECONDS
    assert conf.consume_confirmation_token(token, "fill_applications") is True
    # Tek kullanimlik: ikinci kullanim reddedilir.
    assert conf.consume_confirmation_token(token, "fill_applications") is False


def test_unknown_token_rejected():
    assert conf.consume_confirmation_token("nope", "fill_applications") is False
    assert conf.consume_confirmation_token(None, "fill_applications") is False
    assert conf.consume_confirmation_token("", "submit", "app-1") is False


def test_token_bound_to_action():
    token, _ = conf.mint_confirmation_token("fill_applications")
    assert conf.consume_confirmation_token(token, "submit_application", None) is False


def test_token_bound_to_application():
    token, _ = conf.mint_confirmation_token("submit", "app-1")
    assert conf.consume_confirmation_token(token, "submit", "app-2") is False
    assert conf.consume_confirmation_token(token, "submit", "app-1") is True


def test_expired_token_rejected():
    token, _ = conf.mint_confirmation_token("submit", "app-1")
    conf._tokens[token]["expires_at"] = 0.0
    assert conf.consume_confirmation_token(token, "submit", "app-1") is False


def test_unconfirmable_action_raises():
    import pytest

    with pytest.raises(ValueError):
        conf.mint_confirmation_token("discover")
    with pytest.raises(ValueError):
        conf.mint_confirmation_token("explode")
