"""Adapter resolution: first matching adapter wins, generic is always last."""
from .base import SiteAdapter
from .generic import GenericAdapter
from .workable import WorkableAdapter

_ADAPTERS = [WorkableAdapter, GenericAdapter]  # generic her zaman son


def resolve(url: str) -> SiteAdapter:
    return next(adapter for adapter in _ADAPTERS if adapter.matches(url))()
