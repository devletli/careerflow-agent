"""Adapter resolution: first matching adapter wins, generic is the fallback."""
from browser.site_adapters.base import SiteAdapter
from browser.site_adapters.generic import GenericAdapter
from browser.site_adapters.greenhouse import GreenhouseAdapter
from browser.site_adapters.lever import LeverAdapter
from browser.site_adapters.workable import WorkableAdapter

_ADAPTERS: list[SiteAdapter] = []


def register(adapter: SiteAdapter) -> None:
    _ADAPTERS.append(adapter)


def resolve(url: str) -> SiteAdapter:
    for adapter in _ADAPTERS:
        if adapter.name != "generic" and adapter.matches(url):
            return adapter
    return next(adapter for adapter in _ADAPTERS if adapter.name == "generic")


register(WorkableAdapter())
register(GreenhouseAdapter())
register(LeverAdapter())
register(GenericAdapter())
