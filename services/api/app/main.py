"""AI Job Agent API — composition root (Gorev 3).

Only wiring lives here: app creation, lifespan, exception handlers,
middleware, router registration, and the single unprotected /health probe.
All /api/* routes live in app/routers/ with router-level API-key auth.
"""
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.deps import minio_client, redis_bus
from app.errors import DomainError, domain_error_handler, unhandled_handler
from app.routers import (
    applications_actions,
    applications_core,
    applications_documents,
    confirmations,
    documents,
    events,
    jobs,
    pipeline,
    status,
)
from shared.config import settings
from shared.db.session import check_db_health

logger = logging.getLogger("api")

# Re-exported for existing test patch targets (same singleton instances).
__all__ = ["app", "redis_bus", "minio_client"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Faz 1C: LLM modelini acilista dogrula; boot asla dusmez.
    try:
        from shared.llm.models import validate_llm_at_startup

        await validate_llm_at_startup()
    except Exception as exc:  # noqa: BLE001 - dogrulama best-effort
        logger.warning("LLM startup validation skipped: %s", exc)
    yield


app = FastAPI(
    title="AI Job Agent API",
    description="Control and monitoring REST API for AI Job Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_exception_handler(DomainError, domain_error_handler)
app.add_exception_handler(Exception, unhandled_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """B4: X-Correlation-ID'yi al/uret, log context'ine yaz, yanita ekle."""
    from shared.infra.jsonlog import correlation

    cid = request.headers.get("X-Correlation-ID") or f"req-{uuid4().hex[:12]}"
    with correlation(cid, ""):
        response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response


@app.get("/health")
async def health() -> JSONResponse:
    """Health check validating connectivity to PostgreSQL, Redis, and MinIO."""
    db_healthy = await check_db_health()
    redis_healthy = await redis_bus.ping()
    minio_healthy = minio_client.check_health()

    overall = db_healthy and redis_healthy and minio_healthy
    status_code = 200 if overall else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if overall else "degraded",
            "dependencies": {
                "postgres": db_healthy,
                "redis": redis_healthy,
                "minio": minio_healthy,
            },
        },
    )


for _router in (status, jobs, applications_core, applications_actions, applications_documents, documents, events, pipeline, confirmations):
    app.include_router(_router.router)
