import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional

import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from browser.site_adapters.discovery.text_utils import html_to_text
from shared.contracts.fingerprint import compute_job_fingerprint
from shared.contracts.models import NormalizedJob

logger = logging.getLogger(__name__)

BA_BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4"
BA_PUBLIC_JOB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
# Public client key used by the Bundesagentur job-search web frontend.
BA_API_KEY = "jobboerse-jobsuche"
_REMOTE_HINTS = ("remote", "homeoffice", "home office", "home-office", "mobiles arbeiten")


def _format_location(arbeitsort: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(arbeitsort, dict):
        return None
    parts = [" ".join(p for p in (arbeitsort.get("plz"), arbeitsort.get("ort")) if p)]
    if arbeitsort.get("region"):
        parts.append(arbeitsort["region"])
    text = ", ".join(p for p in parts if p).strip()
    return text[:255] or None


def normalize_ba_item(
    item: Dict[str, Any],
    description: Optional[str] = None,
    source_name: str = "bundesagentur",
) -> Optional[NormalizedJob]:
    """Maps one Bundesagentur search hit to a NormalizedJob (None if unusable)."""
    refnr = item.get("refnr") or ""
    title = (item.get("titel") or item.get("beruf") or "").strip()[:255]
    company = (item.get("arbeitgeber") or "").strip()[:255]
    if not (refnr and title):
        return None

    public_url = BA_PUBLIC_JOB_URL.format(refnr=refnr)
    application_url = item.get("externeUrl") or public_url
    remote = any(hint in title.lower() for hint in _REMOTE_HINTS)

    return NormalizedJob(
        source=source_name,
        source_job_id=refnr,
        company=company or "Unknown",
        title=title,
        url=public_url,
        application_url=application_url,
        location=_format_location(item.get("arbeitsort")),
        remote_status="remote" if remote else "onsite",
        description=description or None,
        job_fingerprint=compute_job_fingerprint(company, title, application_url),
        publication_metadata={
            "published": item.get("aktuelleVeroeffentlichungsdatum"),
            "start_date": item.get("eintrittsdatum"),
            "modified": item.get("modifikationsTimestamp"),
            "beruf": item.get("beruf"),
        },
        raw_data=item,
    )


class BundesagenturAdapter(JobSourceAdapter):
    """
    Bundesagentur für Arbeit job search (largest German job database).
    Search is server-side (`was` = what, `wo` = where); descriptions come from the
    per-job details endpoint and can be skipped with fetch_details=False.
    """

    def __init__(
        self,
        max_pages: int = 5,
        fetch_details: bool = True,
        detail_concurrency: int = 5,
        published_within_days: Optional[int] = 30,
        radius_km: Optional[int] = 25,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.max_pages = max_pages
        self.fetch_details = fetch_details
        self.detail_concurrency = detail_concurrency
        self.published_within_days = published_within_days
        self.radius_km = radius_km
        self._transport = transport  # injectable for tests (httpx.MockTransport)

    @property
    def source_name(self) -> str:
        return "bundesagentur"

    async def _fetch_description(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore, refnr: str
    ) -> Optional[str]:
        encoded = base64.b64encode(refnr.encode("utf-8")).decode("ascii")
        async with sem:
            try:
                res = await client.get(f"{BA_BASE_URL}/jobdetails/{encoded}")
                if res.status_code != 200:
                    return None
                return html_to_text(res.json().get("stellenbeschreibung") or "") or None
            except Exception as e:
                logger.debug("Bundesagentur detail fetch failed for %s: %s", refnr, e)
                return None

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        fetch_details = kwargs.get("fetch_details", self.fetch_details)
        page_size = max(1, min(limit, 100))
        hits: List[Dict[str, Any]] = []
        seen = set()

        # NOTE: rest.arbeitsagentur.de is bot-protected; requests with the default
        # httpx User-Agent are routinely rejected (403/disconnect). Use the same
        # UA as the public job-search web frontend.
        headers = {
            "X-API-Key": BA_API_KEY,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Origin": "https://www.arbeitsagentur.de",
            "Referer": "https://www.arbeitsagentur.de/",
        }
        async with httpx.AsyncClient(timeout=15.0, headers=headers, transport=self._transport) as client:
            for page in range(1, self.max_pages + 1):
                if len(hits) >= limit:
                    break
                params: Dict[str, Any] = {"angebotsart": 1, "page": page, "size": page_size}
                if query:
                    params["was"] = query
                if location:
                    params["wo"] = location
                    if self.radius_km:
                        params["umkreis"] = self.radius_km
                if self.published_within_days:
                    params["veroeffentlichtseit"] = self.published_within_days

                try:
                    res = await client.get(f"{BA_BASE_URL}/jobs", params=params)
                    if res.status_code != 200:
                        logger.warning("Bundesagentur search returned HTTP %s", res.status_code)
                        break
                    items = res.json().get("stellenangebote") or []
                except Exception as e:
                    logger.warning("Error discovering Bundesagentur jobs (page %s): %s", page, e)
                    break

                for item in items:
                    refnr = item.get("refnr")
                    if refnr and refnr not in seen:
                        seen.add(refnr)
                        hits.append(item)
                        if len(hits) >= limit:
                            break

                if len(items) < page_size:
                    break

            descriptions: Dict[str, Optional[str]] = {}
            if fetch_details and hits:
                sem = asyncio.Semaphore(max(1, self.detail_concurrency))
                results = await asyncio.gather(
                    *(self._fetch_description(client, sem, h["refnr"]) for h in hits)
                )
                descriptions = {h["refnr"]: d for h, d in zip(hits, results)}

        jobs: List[NormalizedJob] = []
        for hit in hits:
            job = normalize_ba_item(hit, descriptions.get(hit["refnr"]), self.source_name)
            if job is not None:
                jobs.append(job)
        return jobs
