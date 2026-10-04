"""API routers (Gorev 3). Each router carries its own API-key dependency;
only /health (defined in main.py) stays unprotected."""
from app.routers import (
    applications,
    confirmations,
    documents,
    events,
    jobs,
    pipeline,
    status,
)

__all__ = [
    "applications",
    "confirmations",
    "documents",
    "events",
    "jobs",
    "pipeline",
    "status",
]
