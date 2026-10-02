import logging
from typing import Any, List, Optional
import httpx

from browser.site_adapters.discovery.base import JobSourceAdapter
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)

# Sample popular public tech accounts on Workable for continuous discovery
DEFAULT_WORKABLE_ACCOUNTS = [
    "delivery-hero",
    "tier-mobility",
    "babbel",
    "n26",
    "sumup",
    "personio",
    "zalando",
]


class WorkableAdapter(JobSourceAdapter):
    @property
    def source_name(self) -> str:
        return "workable"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        accounts: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        """
        Discovers jobs via official public Workable API:
        https://apply.workable.com/api/v3/accounts/{account}/jobs
        Does not require employer credentials.
        """
        target_accounts = accounts or DEFAULT_WORKABLE_ACCOUNTS
        discovered: List[NormalizedJob] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            for account in target_accounts:
                if len(discovered) >= limit:
                    break

                api_url = f"https://apply.workable.com/api/v3/accounts/{account}/jobs"
                payload = {
                    "query": query or "",
                    "location": [location] if location else [],
                    "department": [],
                    "workplace": [],
                }

                try:
                    res = await client.post(api_url, json=payload)
                    if res.status_code != 200:
                        logger.debug(f"Workable API for {account} returned status {res.status_code}")
                        continue

                    data = res.json()
                    jobs_list = data.get("results", [])
                    company_name = account.replace("-", " ").title()

                    for item in jobs_list:
                        shortcode = item.get("shortcode") or item.get("id", "")
                        title = item.get("title", "")
                        job_url = f"https://apply.workable.com/{account}/j/{shortcode}/"
                        app_url = f"https://apply.workable.com/{account}/j/{shortcode}/apply/"

                        loc_dict = item.get("location") or {}
                        city = loc_dict.get("city", "")
                        country = loc_dict.get("country", "")
                        loc_str = f"{city}, {country}".strip(", ")

                        workplace = item.get("workplace", "onsite")
                        remote_status = "remote" if workplace == "remote" else ("hybrid" if workplace == "hybrid" else "onsite")

                        job_fp = compute_job_fingerprint(company_name, title, app_url)

                        norm_job = NormalizedJob(
                            source=self.source_name,
                            source_job_id=f"{account}:{shortcode}",
                            company=company_name,
                            title=title,
                            url=job_url,
                            application_url=app_url,
                            location=loc_str or None,
                            remote_status=remote_status,
                            description=item.get("description", ""),
                            requirements=item.get("requirements", []),
                            publication_metadata={
                                "department": item.get("department", ""),
                                "published": item.get("published", ""),
                                "account": account,
                            },
                            job_fingerprint=job_fp,
                            raw_data=item,
                        )
                        discovered.append(norm_job)

                        if len(discovered) >= limit:
                            break

                except Exception as e:
                    logger.debug(f"Error discovering Workable jobs for account {account}: {e}")

        return discovered
