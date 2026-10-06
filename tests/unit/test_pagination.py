"""Faz 2: shared pagination helper (offline, no network)."""

import time

import pytest

from browser.site_adapters.discovery.pagination import paginate
from browser.site_adapters.discovery.prefilter import passes_prefilter


@pytest.mark.asyncio
async def test_paginates_until_exhausted_and_respects_cap():
    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": i} for i in range(100, 200)], 3: []}

    async def fetch(p):
        return pages.get(p, [])

    got = [x async for x in paginate(fetch, max_items=150, max_pages=10, delay=0, deadline=time.monotonic() + 60)]
    assert len(got) == 150


@pytest.mark.asyncio
async def test_time_budget_stops_early():
    async def fetch(p):
        return [{"id": p}]

    got = [x async for x in paginate(fetch, max_items=999, max_pages=999, delay=0, deadline=time.monotonic() - 1)]
    assert got == []


def test_prefilter_rejects_excluded_and_mismatched_location():
    prefs = {
        "preferred_roles": ["DevOps Engineer"],
        "excluded_roles": ["Pure Sales"],
        "locations": ["Berlin"],
        "remote": True,
    }
    ok, _ = passes_prefilter(title="DevOps Engineer", location="Berlin", remote_status="onsite", preferences=prefs)
    assert ok
    ok, reason = passes_prefilter(
        title="Pure Sales Rep", location="Berlin", remote_status="onsite", preferences=prefs
    )
    assert not ok and reason.startswith("excluded_role")
    # Remote passes even when the location does not match.
    ok, _ = passes_prefilter(title="DevOps Engineer", location="Paris", remote_status="remote", preferences=prefs)
    assert ok
    ok, reason = passes_prefilter(
        title="DevOps Engineer", location="Paris", remote_status="onsite", preferences=prefs
    )
    assert not ok and reason == "location_mismatch"
    ok, reason = passes_prefilter(title="Accountant", location="Berlin", remote_status="onsite", preferences=prefs)
    assert not ok and reason == "no_preferred_role_match"
