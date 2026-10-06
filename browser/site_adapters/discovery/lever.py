import asyncio
import logging
import time
from typing import Any, List, Optional

import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from browser.site_adapters.discovery.pagination import fetch_with_backoff, time_deadline
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_LEVER_SITES = ["spotify", "atlassian", "cloudflare"]


class LeverAdapter(JobSourceAdapter):
    # api.lever.co robots: Crawl-delay 1 -> board arasi en az 1sn (settings alt siniri 0.2 degil, 1.0).
    def __init__(
        self,
        page_delay: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        from shared.config import settings

        self.page_delay = max(1.0, page_delay if page_delay is not None else settings.DISCOVERY_PAGE_DELAY_SECONDS)
        self._transport = transport

    @property
    def source_name(self) -> str:
        return "lever"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        sites: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        target_sites = sites or DEFAULT_LEVER_SITES
        discovered: List[NormalizedJob] = []
        page_delay = max(1.0, float(kwargs.get("page_delay", self.page_delay)))
        deadline = kwargs.get("deadline", None)
        deadline = deadline if deadline is not None else time_deadline(kwargs.get("time_budget"))

        async with httpx.AsyncClient(timeout=10.0, transport=self._transport) as client:
            for site in target_sites:
                if len(discovered) >= limit or time.monotonic() > deadline:
                    break

                url = f"https://api.lever.co/v0/postings/{site}?mode=json"
                try:
                    res = await fetch_with_backoff(client, "GET", url)
                    if res.status_code != 200:
                        continue

                    postings = res.json()
                    company = site.title()

                    for item in postings:
                        job_id = item.get("id", "")
                        title = item.get("text", "")
                        apply_url = item.get("applyUrl") or item.get("hostedUrl", "")
                        categories = item.get("categories") or {}
                        loc = categories.get("location", "")
                        workplace = categories.get("workplaceType", "")
                        desc = item.get("descriptionPlain") or item.get("description", "")

                        if query and query.lower() not in title.lower():
                            continue

                        job_fp = compute_job_fingerprint(company, title, apply_url)
                        norm_job = NormalizedJob(
                            source=self.source_name,
                            source_job_id=f"{site}:{job_id}",
                            company=company,
                            title=title,
                            url=item.get("hostedUrl", apply_url),
                            application_url=apply_url,
                            location=loc,
                            remote_status="remote" if workplace == "remote" or (loc and "remote" in loc.lower()) else "onsite",
                            description=desc,
                            job_fingerprint=job_fp,
                            publication_metadata={"site": site, "createdAt": item.get("createdAt")},
                            raw_data=item,
                        )
                        discovered.append(norm_job)
                        if len(discovered) >= limit:
                            break
                except Exception as e:
                    logger.debug(f"Error discovering Lever jobs for {site}: {e}")
                await asyncio.sleep(page_delay)

        return discovered
