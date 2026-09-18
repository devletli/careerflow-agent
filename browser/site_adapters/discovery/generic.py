import json
import logging
from typing import Any, Dict, List, Optional
import httpx
from bs4 import BeautifulSoup

from browser.site_adapters.discovery.base import JobSourceAdapter
from shared.contracts.models import NormalizedJob
from shared.contracts.fingerprint import compute_job_fingerprint

logger = logging.getLogger(__name__)


class GenericJobAdapter(JobSourceAdapter):
    @property
    def source_name(self) -> str:
        return "generic"

    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        """Discovers jobs from generic HTML pages using Schema.org JobPosting JSON-LD."""
        target_urls = urls or []
        discovered: List[NormalizedJob] = []

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            for url in target_urls:
                if len(discovered) >= limit:
                    break

                try:
                    res = await client.get(url)
                    if res.status_code != 200:
                        continue

                    soup = BeautifulSoup(res.text, "html.parser")
                    # Search for schema.org JobPosting in <script type="application/ld+json">
                    for script in soup.find_all("script", type="application/ld+json"):
                        try:
                            data = json.loads(script.string or "{}")
                            if isinstance(data, list):
                                items = data
                            elif isinstance(data, dict):
                                items = [data]
                            else:
                                items = []

                            for item in items:
                                if item.get("@type") == "JobPosting":
                                    title = item.get("title", "")
                                    company = (
                                        item.get("hiringOrganization", {}).get("name")
                                        if isinstance(item.get("hiringOrganization"), dict)
                                        else "Unknown"
                                    )
                                    app_url = item.get("url") or url
                                    job_id = item.get("identifier", {}).get("value") if isinstance(item.get("identifier"), dict) else app_url
                                    job_fp = compute_job_fingerprint(company, title, app_url)

                                    norm_job = NormalizedJob(
                                        source=self.source_name,
                                        source_job_id=str(job_id),
                                        company=company,
                                        title=title,
                                        url=url,
                                        application_url=app_url,
                                        description=item.get("description", ""),
                                        job_fingerprint=job_fp,
                                        raw_data=item,
                                    )
                                    discovered.append(norm_job)
                                    if len(discovered) >= limit:
                                        break
                        except json.JSONDecodeError:
                            continue
                except Exception as e:
                    logger.debug(f"Error parsing generic jobs at {url}: {e}")

        return discovered
