import logging
from typing import Any, List, Optional
import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_GREENHOUSE_BOARDS = [
    "gitlab",
    "canonical",
    "elastic",
    "automattic",
]


class GreenhouseAdapter(JobSourceAdapter):
    @property
    def source_name(self) -> str:
        return "greenhouse"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        boards: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        """Discovers jobs via official public Greenhouse API."""
        target_boards = boards or DEFAULT_GREENHOUSE_BOARDS
        discovered: List[NormalizedJob] = []

        headers = {"Accept": "application/json"}
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            for board in target_boards:
                if len(discovered) >= limit:
                    break

                url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
                try:
                    res = await client.get(url)
                    if res.status_code != 200:
                        continue

                    data = res.json()
                    jobs_list = data.get("jobs", [])
                    company = board.title()

                    for item in jobs_list:
                        job_id = str(item.get("id"))
                        title = item.get("title", "")
                        app_url = item.get("absolute_url", f"https://boards.greenhouse.io/{board}/jobs/{job_id}")
                        loc = (item.get("location") or {}).get("name")

                        if query and query.lower() not in title.lower():
                            continue

                        job_fp = compute_job_fingerprint(company, title, app_url)
                        norm_job = NormalizedJob(
                            source=self.source_name,
                            source_job_id=f"{board}:{job_id}",
                            company=company,
                            title=title,
                            url=app_url,
                            application_url=app_url,
                            location=loc,
                            remote_status="remote" if loc and "remote" in loc.lower() else "onsite",
                            description=item.get("content", ""),
                            job_fingerprint=job_fp,
                            publication_metadata={"board": board, "updated_at": item.get("updated_at")},
                            raw_data=item,
                        )
                        discovered.append(norm_job)
                        if len(discovered) >= limit:
                            break
                except Exception as e:
                    logger.debug(f"Error discovering Greenhouse jobs for {board}: {e}")

        return discovered
