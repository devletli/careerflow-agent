"""Central API error handling (yama.md Faz 3-C).

DomainError carries an explicit HTTP status + machine-readable code so
handlers stay uniform. Unhandled exceptions become a generic 500 without
leaking internals; FastAPI HTTPException responses are untouched.
"""
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("api")


class DomainError(Exception):
    status = 400
    code = "domain_error"


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        {"error": exc.code, "detail": str(exc)},
        status_code=exc.status,
    )


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled", extra={"path": request.url.path})
    return JSONResponse({"error": "internal_error"}, status_code=500)
