import base64

import httpx

from browser.site_adapters.discovery.arbeitnow import ArbeitnowAdapter, normalize_arbeitnow_item
from browser.site_adapters.discovery.bundesagentur import (
    BA_API_KEY,
    BundesagenturAdapter,
    normalize_ba_item,
)
from browser.site_adapters.discovery.text_utils import html_to_text


# ---------------------------------------------------------------- text_utils

def test_html_to_text_basic():
    html = "<p>Your tasks:</p><ul><li>Build <b>MLOps</b> pipelines</li><li>Run K8s &amp; CI/CD</li></ul>"
    text = html_to_text(html)
    assert "Your tasks:" in text
    assert "- Build MLOps pipelines" in text
    assert "- Run K8s & CI/CD" in text
    assert "<" not in text


def test_html_to_text_empty():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""


# ---------------------------------------------------------------- Arbeitnow

def _an_item(slug, title, tags=None, remote=False, location="Berlin", company="Acme GmbH"):
    return {
        "slug": slug,
        "company_name": company,
        "title": title,
        "description": f"<p>{title} wanted</p>",
        "remote": remote,
        "url": f"https://www.arbeitnow.com/jobs/{slug}",
        "tags": tags or [],
        "job_types": ["full time"],
        "location": location,
        "created_at": 1759400000,
    }


def _an_transport(pages):
    """pages: list of payloads; page N is pages[N-1]. Records requested pages."""
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        requested.append(page)
        if page > len(pages):
            return httpx.Response(404)
        return httpx.Response(200, json=pages[page - 1])

    return httpx.MockTransport(handler), requested


def test_normalize_arbeitnow_item():
    job = normalize_arbeitnow_item(_an_item("mlops-eng-1", "MLOps Engineer", remote=True))
    assert job.source == "arbeitnow"
    assert job.source_job_id == "mlops-eng-1"
    assert job.company == "Acme GmbH"
    assert job.remote_status == "remote"
    assert job.description == "MLOps Engineer wanted"
    assert job.application_url == job.url
    assert len(job.job_fingerprint) == 64
    assert job.publication_metadata["created_at"].startswith("2025-")


def test_normalize_arbeitnow_item_rejects_incomplete():
    assert normalize_arbeitnow_item({"title": "No slug"}) is None
    assert normalize_arbeitnow_item({"slug": "x", "title": "No url"}) is None


def test_normalize_arbeitnow_item_truncates_long_fields():
    job = normalize_arbeitnow_item(_an_item("long", "T" * 400, company="C" * 400, location="L" * 400))
    assert len(job.title) == 255 and len(job.company) == 255 and len(job.location) == 255


async def test_arbeitnow_filters_by_query_and_location():
    items = [
        _an_item("a", "Senior MLOps Engineer", location="Berlin"),
        _an_item("b", "Accountant", location="Berlin"),
        _an_item("c", "MLOps Engineer", location="Munich"),
        _an_item("d", "Platform Engineer", tags=["MLOps", "Kubernetes"], remote=True, location="Remote"),
    ]
    transport, _ = _an_transport([{"data": items, "links": {"next": None}}])
    jobs = await ArbeitnowAdapter(transport=transport).discover_jobs(query="MLOps", location="Berlin")
    assert [j.source_job_id for j in jobs] == ["a", "d"]  # Munich excluded, remote kept via tag match


async def test_arbeitnow_no_filters_returns_all_and_respects_limit():
    items = [_an_item(f"j{i}", f"Engineer {i}") for i in range(5)]
    transport, _ = _an_transport([{"data": items, "links": {"next": None}}])
    jobs = await ArbeitnowAdapter(transport=transport).discover_jobs(limit=3)
    assert len(jobs) == 3


async def test_arbeitnow_paginates_until_no_next_and_dedupes():
    page1 = {"data": [_an_item("a", "AI Engineer"), _an_item("b", "AI Engineer II")], "links": {"next": "x"}}
    page2 = {"data": [_an_item("b", "AI Engineer II"), _an_item("c", "AI Architect")], "links": {"next": None}}
    transport, requested = _an_transport([page1, page2])
    jobs = await ArbeitnowAdapter(transport=transport).discover_jobs(query="AI", limit=50)
    assert [j.source_job_id for j in jobs] == ["a", "b", "c"]
    assert requested == [1, 2]


async def test_arbeitnow_http_error_returns_empty():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    assert await ArbeitnowAdapter(transport=transport).discover_jobs(query="AI") == []


# ---------------------------------------------------------------- Bundesagentur

def _ba_hit(refnr, titel, arbeitgeber="Beispiel AG", ort="Berlin", plz="10115", **extra):
    hit = {
        "refnr": refnr,
        "titel": titel,
        "beruf": "Informatiker/in",
        "arbeitgeber": arbeitgeber,
        "arbeitsort": {"plz": plz, "ort": ort, "region": "Berlin"},
        "aktuelleVeroeffentlichungsdatum": "2026-09-30",
        "eintrittsdatum": "2026-11-01",
    }
    hit.update(extra)
    return hit


class _BaServer:
    def __init__(self, pages, details=None, detail_status=200):
        self.pages = pages
        self.details = details or {}
        self.detail_status = detail_status
        self.search_requests = []
        self.detail_requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pc/v4/jobs"):
            self.search_requests.append(request)
            page = int(request.url.params["page"])
            hits = self.pages[page - 1] if page <= len(self.pages) else []
            return httpx.Response(200, json={"stellenangebote": hits})
        if "/pc/v4/jobdetails/" in path:
            encoded = path.rsplit("/", 1)[1]
            refnr = base64.b64decode(encoded).decode()
            self.detail_requests.append(refnr)
            if self.detail_status != 200:
                return httpx.Response(self.detail_status)
            return httpx.Response(200, json={"stellenbeschreibung": self.details.get(refnr, "")})
        return httpx.Response(404)


def test_normalize_ba_item():
    job = normalize_ba_item(_ba_hit("10001-123-S", "Senior MLOps Engineer (m/w/d) Homeoffice"), "Beschreibung")
    assert job.source == "bundesagentur"
    assert job.source_job_id == "10001-123-S"
    assert job.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-123-S"
    assert job.application_url == job.url
    assert job.location == "10115 Berlin, Berlin"
    assert job.remote_status == "remote"
    assert job.description == "Beschreibung"
    assert job.publication_metadata["published"] == "2026-09-30"


def test_normalize_ba_item_external_url_and_fallbacks():
    job = normalize_ba_item({"refnr": "r1", "beruf": "Fachinformatiker", "externeUrl": "https://karriere.example.com/42"})
    assert job.title == "Fachinformatiker"  # falls back to `beruf`
    assert job.company == "Unknown"
    assert job.application_url == "https://karriere.example.com/42"
    assert job.url.endswith("/r1")
    assert job.remote_status == "onsite"
    assert job.location is None
    assert normalize_ba_item({"titel": "no refnr"}) is None


async def test_ba_search_params_header_and_details():
    server = _BaServer(
        pages=[[_ba_hit("r1", "MLOps Engineer"), _ba_hit("r2", "AI Architect")]],
        details={"r1": "<p>Python &amp; Kubernetes</p>", "r2": "Plain text"},
    )
    adapter = BundesagenturAdapter(transport=httpx.MockTransport(server))
    jobs = await adapter.discover_jobs(query="MLOps", location="Berlin", limit=20)

    assert [j.source_job_id for j in jobs] == ["r1", "r2"]
    assert jobs[0].description == "Python & Kubernetes"
    assert jobs[1].description == "Plain text"
    assert sorted(server.detail_requests) == ["r1", "r2"]

    req = server.search_requests[0]
    assert req.headers["X-API-Key"] == BA_API_KEY
    params = req.url.params
    assert params["was"] == "MLOps" and params["wo"] == "Berlin"
    assert params["umkreis"] == "25" and params["veroeffentlichtseit"] == "30"
    assert params["angebotsart"] == "1" and params["size"] == "20"


async def test_ba_without_location_omits_wo_and_radius():
    server = _BaServer(pages=[[_ba_hit("r1", "DevOps Engineer")]])
    await BundesagenturAdapter(fetch_details=False, transport=httpx.MockTransport(server)).discover_jobs(query="DevOps")
    params = server.search_requests[0].url.params
    assert "wo" not in params and "umkreis" not in params


async def test_ba_fetch_details_disabled():
    server = _BaServer(pages=[[_ba_hit("r1", "DevOps Engineer")]])
    adapter = BundesagenturAdapter(fetch_details=False, transport=httpx.MockTransport(server))
    jobs = await adapter.discover_jobs(query="DevOps")
    assert jobs[0].description is None
    assert server.detail_requests == []


async def test_ba_detail_failure_is_tolerated():
    server = _BaServer(pages=[[_ba_hit("r1", "DevOps Engineer")]], detail_status=500)
    jobs = await BundesagenturAdapter(transport=httpx.MockTransport(server)).discover_jobs(query="DevOps")
    assert len(jobs) == 1 and jobs[0].description is None


async def test_ba_paginates_until_short_page_and_dedupes():
    # limit > 100 -> page_size is capped at 100, so a second page is needed.
    page1 = [_ba_hit(f"r{i}", f"Engineer {i}") for i in range(100)]
    page2 = [_ba_hit("r0", "Engineer 0"), _ba_hit("r100", "Engineer 100"), _ba_hit("r101", "Engineer 101")]
    server = _BaServer(pages=[page1, page2])
    adapter = BundesagenturAdapter(fetch_details=False, transport=httpx.MockTransport(server))
    jobs = await adapter.discover_jobs(query="Engineer", limit=150)

    assert len(jobs) == 102  # duplicate r0 on page 2 is dropped
    assert len({j.source_job_id for j in jobs}) == 102
    assert [int(r.url.params["page"]) for r in server.search_requests] == [1, 2]  # short page 2 ends the loop


async def test_ba_stops_once_limit_reached():
    page1 = [_ba_hit(f"r{i}", f"Engineer {i}") for i in range(10)]
    server = _BaServer(pages=[page1, page1])
    adapter = BundesagenturAdapter(fetch_details=False, transport=httpx.MockTransport(server))
    jobs = await adapter.discover_jobs(query="Engineer", limit=3)
    assert len(jobs) == 3
    assert len(server.search_requests) == 1


async def test_ba_search_http_error_returns_empty():
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    assert await BundesagenturAdapter(transport=transport).discover_jobs(query="AI") == []
