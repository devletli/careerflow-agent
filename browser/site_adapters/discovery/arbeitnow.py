import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from browser.site_adapters.discovery.pagination import fetch_with_backoff, time_deadline
from browser.site_adapters.discovery.text_utils import html_to_text
from shared.contracts.fingerprint import compute_job_fingerprint
from shared.contracts.models import NormalizedJob

logger = logging.getLogger(__name__)

ARBEITNOW_API_URL = "https://www.arbeitnow.com/api/job-board-api"


def _matches(haystack_parts: List[str], needle: Optional[str]) -> bool:
    """Case-insensitive match: every whitespace-separated word of `needle` must occur."""
    if not needle:
        return True
    haystack = " ".join(p for p in haystack_parts if p).lower()
    return all(word in haystack for word in needle.lower().split())


def normalize_arbeitnow_item(item: Dict[str, Any], source_name: str = "arbeitnow") -> Optional[NormalizedJob]:
    """Maps one Arbeitnow job-board entry to a NormalizedJob (None if unusable)."""
    slug = item.get("slug") or ""
    title = (item.get("title") or "").strip()[:255]
    company = (item.get("company_name") or "").strip()[:255]
    url = item.get("url") or ""
    if not (slug and title and url):
        return None

    created = item.get("created_at")
    created_iso = None
    if isinstance(created, (int, float)):
        created_iso = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()

    return NormalizedJob(
        source=source_name,
        source_job_id=slug,
        company=company or "Unknown",
        title=title,
        url=url,
        application_url=url,
        location=(item.get("location") or "").strip()[:255] or None,
        remote_status="remote" if item.get("remote") else "onsite",
        description=html_to_text(item.get("description") or ""),
        job_fingerprint=compute_job_fingerprint(company, title, url),
        publication_metadata={
            "created_at": created_iso,
            "tags": item.get("tags") or [],
            "job_types": item.get("job_types") or [],
        },
        raw_data=item,
    )


class ArbeitnowAdapter(JobSourceAdapter):
    """
    Public Arbeitnow job-board API (Germany/EU focused, no API key needed).
    The API has no server-side search, so `query`/`location` are filtered client-side
    across a bounded number of result pages.
    """

    def __init__(
        self,
        max_pages: Optional[int] = None,
        page_delay: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        from shared.config import settings

        self.max_pages = max_pages if max_pages is not None else settings.DISCOVERY_MAX_PAGES_PER_SOURCE
        self.page_delay = page_delay if page_delay is not None else settings.DISCOVERY_PAGE_DELAY_SECONDS
        self._transport = transport  # injectable for tests (httpx.MockTransport)

    @property
    def source_name(self) -> str:
        return "arbeitnow"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        discovered: List[NormalizedJob] = []
        seen_slugs = set()
        max_pages = int(kwargs.get("max_pages", self.max_pages))
        page_delay = float(kwargs.get("page_delay", self.page_delay))
        deadline = kwargs.get("deadline", None)
        deadline = deadline if deadline is not None else time_deadline(kwargs.get("time_budget"))

        async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
            for page in range(1, max_pages + 1):
                if len(discovered) >= limit or time.monotonic() > deadline:
                    break
                try:
                    res = await fetch_with_backoff(client, "GET", ARBEITNOW_API_URL, params={"page": page})
                    if res.status_code != 200:
                        logger.warning("Arbeitnow page %s returned HTTP %s", page, res.status_code)
                        break
                    payload = res.json()
                except Exception as e:
                    logger.warning("Error discovering Arbeitnow jobs (page %s): %s", page, e)
                    break

                items = payload.get("data") or []
                if not items:
                    break

                for item in items:
                    job = normalize_arbeitnow_item(item, self.source_name)
                    if job is None or job.source_job_id in seen_slugs:
                        continue
                    if not _matches(
                        [job.title, " ".join(item.get("tags") or []), job.description or ""], query
                    ):
                        continue
                    if not _matches([job.location or ""], location) and not (
                        location and job.remote_status == "remote"
                    ):
                        continue
                    seen_slugs.add(job.source_job_id)
                    discovered.append(job)
                    if len(discovered) >= limit:
                        break

                if not (payload.get("links") or {}).get("next"):
                    break
                await asyncio.sleep(page_delay)

        return discovered
