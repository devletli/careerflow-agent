"""Single-use confirmation tokens, Redis-backed (B2).

UI onayina guvenmek yerine, "Gonder" ve "Playwright ile Doldur" aksiyonlari
sunucu tarafindan uretilen tek kullanimlik token ister. Tuketim
Redis GETDEL ile atomiktir: okuma+silme tek komut oldugu icin ayni
token iki eszamanli istekte iki kez gecerli olamaz.

Token duz metin saklanmaz: anahtar sha256(token)'dir, deger
`{"a": action, "app": application_id}` JSON'udur. TTL 300 sn.

Not: API tek surecte calissa bile Redis zorunludur; boylece worker/
replica sayisi artsa da tek-kullanim garantisi bozulmaz.
"""
import hashlib
import json
import secrets
from typing import Any, Optional

TOKEN_TTL_SECONDS = 300

# Token uretilebilen aksiyonlar: pipeline fill/submit + per-app execute submit.
CONFIRMABLE_ACTIONS = frozenset(
    {"fill_applications", "submit_application", "submit"}
)


def _key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"confirm:{digest}"


def _value(action: str, application_id: Optional[str]) -> str:
    return json.dumps(
        {
            "a": action,
            "app": str(application_id) if application_id is not None else None,
        }
    )


async def mint_confirmation_token(
    redis: Any, action: str, application_id: Optional[str] = None
) -> tuple[str, int]:
    """Yeni tek kullanimlik token uretir; desteklenmeyen aksiyonda ValueError."""
    if action not in CONFIRMABLE_ACTIONS:
        raise ValueError(f"Action is not confirmable: {action}.")
    token = secrets.token_urlsafe(32)
    await redis.set(_key(token), _value(action, application_id), ex=TOKEN_TTL_SECONDS)
    return token, TOKEN_TTL_SECONDS


async def consume_confirmation_token(
    redis: Any, token: Optional[str], action: str, application_id: Optional[str] = None
) -> bool:
    """Token gecerliyse ATOMIK tuketip True dondurur; aksi halde False."""
    if not token:
        return False
    raw = await redis.getdel(_key(token))
    if raw is None:
        return False
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return stored == {
        "a": action,
        "app": str(application_id) if application_id is not None else None,
    }
