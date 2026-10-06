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

DEFAULT_ASHBY_BOARDS = ["openai", "replicate", "postman"]


class AshbyAdapter(JobSourceAdapter):
    def __init__(
        self,
        page_delay: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        from shared.config import settings

        self.page_delay = page_delay if page_delay is not None else settings.DISCOVERY_PAGE_DELAY_SECONDS
        self._transport = transport

    @property
    def source_name(self) -> str:
        return "ashby"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        boards: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        target_boards = boards or DEFAULT_ASHBY_BOARDS
        discovered: List[NormalizedJob] = []
        page_delay = float(kwargs.get("page_delay", self.page_delay))
        deadline = kwargs.get("deadline", None)
        deadline = deadline if deadline is not None else time_deadline(kwargs.get("time_budget"))

        async with httpx.AsyncClient(timeout=10.0, transport=self._transport) as client:
            for board in target_boards:
                if len(discovered) >= limit or time.monotonic() > deadline:
                    break

                url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
                try:
                    res = await fetch_with_backoff(client, "GET", url)
                    if res.status_code != 200:
                        continue

                    data = res.json()
                    jobs_list = data.get("jobs", [])
                    company = board.title()

                    for item in jobs_list:
                        job_id = item.get("id", "")
                        title = item.get("title", "")
                        app_url = item.get("jobUrl", f"https://jobs.ashbyhq.com/{board}/{job_id}/application")
                        loc = item.get("location", "")
                        is_remote = item.get("isRemote", False)

                        if query and query.lower() not in title.lower():
                            continue

                        job_fp = compute_job_fingerprint(company, title, app_url)
                        norm_job = NormalizedJob(
                            source=self.source_name,
                            source_job_id=f"{board}:{job_id}",
                            company=company,
                            title=title,
                            url=item.get("jobUrl", app_url),
                            application_url=app_url,
                            location=loc,
                            remote_status="remote" if is_remote else "onsite",
                            description=item.get("descriptionHtml", ""),
                            job_fingerprint=job_fp,
                            publication_metadata={"board": board, "publishedAt": item.get("publishedAt")},
                            raw_data=item,
                        )
                        discovered.append(norm_job)
                        if len(discovered) >= limit:
                            break
                except Exception as e:
                    logger.debug(f"Error discovering Ashby jobs for {board}: {e}")
                await asyncio.sleep(page_delay)

        return discovered
