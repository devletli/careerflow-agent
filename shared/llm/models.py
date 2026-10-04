"""LLM model dogrulamasi (Faz 1C).

Acilista `LLM_MODEL` degerinin saglayicide gercekten var oldugu kanitlanir.
Gecersiz/eksik yapilandirmada net hata loglanir ve deterministik moda
gecilir (skor hesabi etkilenmez); hata sessizce yutulmaz.

Son dogrulama sonucu `llm_status()` ile okunur; API `/api/v1/status`
uzerinden dashboardda gosterilir.
"""

import asyncio
import logging
from typing import Any, Optional

from shared.config import settings

log = logging.getLogger("llm.models")

_llm_status: dict[str, Any] = {
    "state": "unknown",
    "reason": "not validated yet",
    "model": None,
}


def resolve_model(client: Any, wanted: str) -> Optional[str]:
    """Istenen model saglayici listesinde varsa adini dondur, yoksa None.

    `client` google-genai `Client` (senkron `models.list`). Ag hatasi dahil
    her basarisizlikta hata loglanir ve None donulur.
    """
    try:
        available = {m.name.removeprefix("models/") for m in client.models.list()}
    except Exception as exc:
        log.error("LLM model listesi alinamadi: %s", exc)
        return None
    if wanted in available:
        return wanted
    log.error(
        "LLM_MODEL=%r gecersiz. Kullanilabilir flash modeller: %s",
        wanted,
        sorted(n for n in available if "flash" in n),
    )
    return None


async def validate_llm_at_startup() -> dict[str, Any]:
    """Acilis dogrulamasi; sonucu modulu globalinde saklar ve dondurur.

    Asla exception yukseltmez: basarisizlik her zaman
    `{"state": "disabled", "reason": ...}` olarak kaydedilir.
    """
    global _llm_status
    try:
        provider = (settings.LLM_PROVIDER or "gemini").lower()
        wanted = settings.LLM_MODEL or ""
        gemini_key = (
            settings.GEMINI_API_KEY.get_secret_value() if settings.GEMINI_API_KEY else None
        )
        if provider != "gemini":
            _llm_status = {
                "state": "disabled",
                "reason": f"provider '{provider}' icin acilis dogrulamasi yok",
                "model": None,
            }
        elif not gemini_key:
            _llm_status = {
                "state": "disabled",
                "reason": "GEMINI_API_KEY yok; LLM aciklamasi kapali",
                "model": None,
            }
        elif not wanted:
            _llm_status = {
                "state": "disabled",
                "reason": "LLM_MODEL bos; LLM aciklamasi kapali",
                "model": None,
            }
        else:
            try:
                from google import genai
            except ImportError:
                _llm_status = {
                    "state": "disabled",
                    "reason": "google-genai paketi kurulu degil",
                    "model": None,
                }
            else:
                client = genai.Client(api_key=gemini_key)
                model = await asyncio.to_thread(resolve_model, client, wanted)
                if model is None:
                    _llm_status = {
                        "state": "disabled",
                        "reason": f"LLM_MODEL={wanted!r} saglayicide bulunamadi",
                        "model": None,
                    }
                else:
                    _llm_status = {
                        "state": "active",
                        "reason": "model saglayici listesinde dogrulandi",
                        "model": model,
                    }
    except Exception as exc:  # acilis dogrulamasi boot'u asla dusurmez
        log.error("LLM acilis dogrulamasi basarisiz: %s", exc)
        _llm_status = {
            "state": "disabled",
            "reason": f"dogrulama hatasi: {exc}",
            "model": None,
        }
    log.info("LLM status: %s (%s)", _llm_status["state"], _llm_status["reason"])
    return dict(_llm_status)


def llm_status() -> dict[str, Any]:
    """Son dogrulama sonucunun kopyasi."""
    return dict(_llm_status)
