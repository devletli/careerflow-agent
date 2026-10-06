import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from browser.site_adapters.discovery.pagination import fetch_with_backoff, time_deadline
from browser.site_adapters.discovery.text_utils import html_to_text
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_SR_COMPANIES = ["visa", "spotify", "ikea"]

SR_PAGE_SIZE = 100


def _sr_location(item: Dict[str, Any]) -> str:
    loc_obj = item.get("location") or {}
    city = loc_obj.get("city", "")
    country = loc_obj.get("country", "")
    return f"{city}, {country}".strip(", ")


class SmartRecruitersAdapter(JobSourceAdapter):
    """SmartRecruiters public postings: paginated list (offset/limit, 100/page,
    no descriptions) + per-posting detail fetch (bounded concurrency)."""

    def __init__(
        self,
        fetch_details: bool = True,
        detail_concurrency: Optional[int] = None,
        page_delay: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        from shared.config import settings

        self.fetch_details = fetch_details
        self.detail_concurrency = (
            detail_concurrency if detail_concurrency is not None else settings.DISCOVERY_DETAIL_CONCURRENCY
        )
        self.page_delay = page_delay if page_delay is not None else settings.DISCOVERY_PAGE_DELAY_SECONDS
        self._transport = transport

    @property
    def source_name(self) -> str:
        return "smartrecruiters"

    async def _fetch_description(self, client: httpx.AsyncClient, sem: asyncio.Semaphore, company: str, posting_id: str) -> str:
        async with sem:
            try:
                res = await fetch_with_backoff(
                    client, "GET", f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"
                )
                if res.status_code != 200:
                    return ""
                data = res.json()
                parts = [
                    data.get("jobDescription") or "",
                    data.get("qualifications") or "",
                    data.get("additionalInformation") or "",
                ]
                return html_to_text("\n".join(p for p in parts if p))
            except Exception as e:
                logger.debug("SmartRecruiters detail fetch failed for %s/%s: %s", company, posting_id, e)
                return ""

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        companies: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        target_companies = companies or DEFAULT_SR_COMPANIES
        fetch_details = kwargs.get("fetch_details", self.fetch_details)
        max_pages = int(kwargs.get("max_pages", 10**9))
        page_delay = float(kwargs.get("page_delay", self.page_delay))
        deadline = kwargs.get("deadline", None)
        deadline = deadline if deadline is not None else time_deadline(kwargs.get("time_budget"))
        discovered: List[NormalizedJob] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(timeout=10.0, transport=self._transport) as client:
            for company in target_companies:
                if len(discovered) >= limit or time.monotonic() > deadline:
                    break
                offset = 0
                pages = 0
                company_name = company.title()
                collected: List[Dict[str, Any]] = []
                while len(discovered) + len(collected) < limit and pages < max_pages:
                    if time.monotonic() > deadline:
                        break
                    params: Dict[str, Any] = {"limit": min(SR_PAGE_SIZE, limit), "offset": offset}
                    if query:
                        params["q"] = query
                    try:
                        res = await fetch_with_backoff(
                            client, "GET", f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                            params=params,
                        )
                        if res.status_code != 200:
                            break
                        data = res.json()
                    except Exception as e:
                        logger.debug(f"Error discovering SmartRecruiters jobs for {company}: {e}")
                        break
                    postings = data.get("content", [])
                    total = data.get("totalFound")
                    if not postings:
                        break
                    for item in postings:
                        key = f"{company}:{item.get('id', '')}"
                        if key not in seen:
                            seen.add(key)
                            collected.append(item)
                            if len(discovered) + len(collected) >= limit:
                                break
                    offset += len(postings)
                    pages += 1
                    # Short page or totalFound reached -> company exhausted.
                    if len(postings) < min(SR_PAGE_SIZE, limit):
                        break
                    if isinstance(total, int) and offset >= total:
                        break
                    await asyncio.sleep(page_delay)

                descriptions: Dict[str, str] = {}
                if fetch_details and collected:
                    sem = asyncio.Semaphore(max(1, int(kwargs.get("detail_concurrency", self.detail_concurrency))))
                    results = await asyncio.gather(
                        *(self._fetch_description(client, sem, company, str(it.get("id", ""))) for it in collected)
                    )
                    descriptions = {str(it.get("id", "")): d for it, d in zip(collected, results)}

                for item in collected:
                    job_id = item.get("id", "")
                    title = item.get("name", "")
                    loc_str = _sr_location(item)
                    app_url = f"https://jobs.smartrecruiters.com/{company}/{job_id}"
                    job_fp = compute_job_fingerprint(company_name, title, app_url)
                    norm_job = NormalizedJob(
                        source=self.source_name,
                        source_job_id=f"{company}:{job_id}",
                        company=company_name,
                        title=title,
                        url=app_url,
                        application_url=app_url,
                        location=loc_str or None,
                        remote_status="remote" if "remote" in loc_str.lower() else "onsite",
                        description=descriptions.get(str(job_id), ""),
                        job_fingerprint=job_fp,
                        publication_metadata={"company": company, "releasedDate": item.get("releasedDate")},
                        raw_data=item,
                    )
                    discovered.append(norm_job)
                    if len(discovered) >= limit:
                        break
                await asyncio.sleep(page_delay)

        return discovered
