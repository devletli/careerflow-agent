"""API key authentication for the control/monitoring API.

The dashboard forwards the shared API_KEY server-side (Next.js middleware),
so the key never reaches the browser. /health stays public for load
balancers and Docker healthchecks.
"""
import hmac

from fastapi import Depends, Header, HTTPException, status

from shared.config import settings


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.API_KEY or not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")


ApiKey = Depends(require_api_key)
