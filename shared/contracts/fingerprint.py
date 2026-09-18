import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "gh_src",
    "lever-source",
    "ashby_jid",
    "fbclid",
    "gclid",
    "mc_eid",
    "trk",
    "original_referer",
}


def canonicalize_url(url: str) -> str:
    """
    Canonicalizes an application/job URL for deterministic deduplication:
    - Strips leading/trailing whitespace
    - Lowercases scheme and hostname
    - Strips standard tracking and campaign parameters
    - Normalizes trailing slashes in path
    - Sorts remaining query parameters
    - Strips fragment identifiers (#)
    """
    if not url or not url.strip():
        return ""

    url = url.strip()
    if not re.match(r"^[a-zA-Z]+://", url):
        url = "https://" + url

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Normalize port if default
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Normalize path
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Strip tracking parameters and sort remaining
    query_params = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = sorted(
        [(k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS]
    )
    clean_query = urlencode(filtered_params)

    # Reassemble without fragment
    return urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))


def compute_job_fingerprint(company: str, title: str, application_url: str) -> str:
    """
    Deterministic job fingerprint according to data-model.md:
    sha256(
      lower(trim(company))
      + "|"
      + lower(trim(title))
      + "|"
      + canonicalize(application_url)
    )
    """
    norm_company = (company or "").strip().lower()
    norm_title = (title or "").strip().lower()
    canonical_url = canonicalize_url(application_url or "")

    raw = f"{norm_company}|{norm_title}|{canonical_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_application_fingerprint(candidate_id: str, job_fingerprint: str) -> str:
    """
    Deterministic application fingerprint according to data-model.md:
    sha256(
      candidate_id
      + "|"
      + job_fingerprint
    )
    """
    norm_candidate = (candidate_id or "").strip()
    norm_job_fp = (job_fingerprint or "").strip()

    raw = f"{norm_candidate}|{norm_job_fp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
