"""API routers (Gorev 3). Each router carries its own API-key dependency;
only /health (defined in main.py) stays unprotected."""
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

__all__ = [
    "applications_actions",
    "applications_core",
    "applications_documents",
    "confirmations",
    "documents",
    "events",
    "jobs",
    "pipeline",
    "status",
]
