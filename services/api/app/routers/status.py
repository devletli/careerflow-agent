"""Service status (router-level API key; /health main.py'de korumasiz)."""
from typing import Any

from fastapi import APIRouter, Depends

from app.security import require_api_key
from shared.config import settings

router = APIRouter(
    prefix="/api/v1",
    tags=["status"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/status")
def status() -> dict[str, Any]:
    from shared.llm.models import llm_status

    return {
        "service": "api",
        "version": "0.1.0",
        "automation_mode": settings.AUTOMATION_MODE,
        "auto_submit": settings.AUTO_SUBMIT,
        "min_match_score": settings.MIN_MATCH_SCORE,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "llm_status": llm_status(),
    }
