"""Single-use confirmation tokens for browser actions (Faz 3B).

UI onayina guvenmek yerine, "Gonder" ve "Playwright ile Doldur" aksiyonlari
sunucu tarafindan uretilen tek kullanimlik token ister:

1. istemci `POST /api/v1/confirmations {action, application_id?}` ile token alir
   (bu istek, kullanicinin dashboarddaki acik onayinin ardindan yapilir),
2. token, aksiyon istegiyle birlikte gonderilir ve ilk kullanimda tuketilir.

Token aksiyona (+ varsa uygulamaya) baglidir, 5 dakika gecerlidir.

Not: depo surec ici (in-memory) tutulur; API tek uvicorn worker ile calir
(`services/api/Dockerfile` CMD'de `--workers` yok). Worker sayisi artarsa
bu depo Redis'e tasinmalidir.
"""

import secrets
import time
from typing import Optional

TOKEN_TTL_SECONDS = 300

# Token uretilebilen aksiyonlar: pipeline fill/submit + per-app execute submit.
CONFIRMABLE_ACTIONS = frozenset(
    {"fill_applications", "submit_application", "submit"}
)

_tokens: dict[str, dict] = {}


def _prune(now: float) -> None:
    expired = [t for t, rec in _tokens.items() if rec["expires_at"] <= now]
    for token in expired:
        del _tokens[token]


def mint_confirmation_token(action: str, application_id: Optional[str] = None) -> tuple[str, int]:
    """Yeni tek kullanimlik token uretir; desteklenmeyen aksiyonda ValueError."""
    if action not in CONFIRMABLE_ACTIONS:
        raise ValueError(f"Action is not confirmable: {action}.")
    now = time.monotonic()
    _prune(now)
    token = secrets.token_urlsafe(32)
    _tokens[token] = {
        "action": action,
        "application_id": str(application_id) if application_id is not None else None,
        "expires_at": now + TOKEN_TTL_SECONDS,
    }
    return token, TOKEN_TTL_SECONDS


def consume_confirmation_token(
    token: Optional[str], action: str, application_id: Optional[str] = None
) -> bool:
    """Token gecerliyse tuketip True dondurur; aksi halde False (tek kullanimlik)."""
    if not token:
        return False
    record = _tokens.get(token)
    if record is None:
        return False
    if record["expires_at"] <= time.monotonic():
        del _tokens[token]
        return False
    if record["action"] != action:
        return False
    expected_app = str(application_id) if application_id is not None else None
    if record["application_id"] != expected_app:
        return False
    # Tek kullanimlik: yalnizca basarili dogrulamada tuket.
    del _tokens[token]
    return True
