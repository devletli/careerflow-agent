import logging
from typing import Any, Dict, List, Optional
import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_LEVER_SITES = ["spotify", "atlassian", "cloudflare"]


class LeverAdapter(JobSourceAdapter):
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

        async with httpx.AsyncClient(timeout=10.0) as client:
            for site in target_sites:
                if len(discovered) >= limit:
                    break

                url = f"https://api.lever.co/v0/postings/{site}?mode=json"
                try:
                    res = await client.get(url)
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

        return discovered
