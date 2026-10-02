import logging
from typing import Any, List, Optional
import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_SR_COMPANIES = ["visa", "spotify", "ikea"]


class SmartRecruitersAdapter(JobSourceAdapter):
    @property
    def source_name(self) -> str:
        return "smartrecruiters"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        companies: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        target_companies = companies or DEFAULT_SR_COMPANIES
        discovered: List[NormalizedJob] = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            for company in target_companies:
                if len(discovered) >= limit:
                    break

                url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
                params = {"q": query} if query else {}
                try:
                    res = await client.get(url, params=params)
                    if res.status_code != 200:
                        continue

                    data = res.json()
                    postings = data.get("content", [])
                    company_name = company.title()

                    for item in postings:
                        job_id = item.get("id", "")
                        title = item.get("name", "")
                        loc_obj = item.get("location") or {}
                        city = loc_obj.get("city", "")
                        country = loc_obj.get("country", "")
                        loc_str = f"{city}, {country}".strip(", ")

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
                            description="",
                            job_fingerprint=job_fp,
                            publication_metadata={"company": company, "releasedDate": item.get("releasedDate")},
                            raw_data=item,
                        )
                        discovered.append(norm_job)
                        if len(discovered) >= limit:
                            break
                except Exception as e:
                    logger.debug(f"Error discovering SmartRecruiters jobs for {company}: {e}")

        return discovered
