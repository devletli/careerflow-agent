import pytest
from shared.contracts.fingerprint import (
    canonicalize_url,
    compute_job_fingerprint,
    compute_application_fingerprint,
)


def test_canonicalize_url_tracking_params():
    raw_url = "https://example.com/jobs/123/?utm_source=linkedin&ref=board&utm_medium=cpc#apply"
    canonical = canonicalize_url(raw_url)
    assert canonical == "https://example.com/jobs/123"
    assert "utm_source" not in canonical
    assert "ref" not in canonical
    assert "#apply" not in canonical


def test_canonicalize_url_query_sorting():
    url1 = "https://example.com/apply?dept=eng&country=DE"
    url2 = "https://example.com/apply?country=DE&dept=eng"
    assert canonicalize_url(url1) == canonicalize_url(url2)


def test_canonicalize_url_trailing_slashes_and_case():
    url1 = "HTTP://EXAMPLE.COM/jobs/engineering/"
    url2 = "https://example.com/jobs/engineering"
    # Schemes differ, but host and trailing slash should normalize
    c1 = canonicalize_url(url1)
    c2 = canonicalize_url(url2)
    assert c1.endswith("/jobs/engineering")
    assert c2.endswith("/jobs/engineering")


def test_compute_job_fingerprint_normalization():
    fp1 = compute_job_fingerprint(
        company="  ACME Corp  ",
        title="Senior AI Engineer  ",
        application_url="https://acme.com/apply/101?utm_campaign=spring",
    )
    fp2 = compute_job_fingerprint(
        company="acme corp",
        title="senior ai engineer",
        application_url="https://acme.com/apply/101",
    )
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex string


def test_compute_job_fingerprint_distinctness():
    fp1 = compute_job_fingerprint("Acme", "Engineer", "https://acme.com/1")
    fp2 = compute_job_fingerprint("Acme", "Manager", "https://acme.com/1")
    fp3 = compute_job_fingerprint("Beta", "Engineer", "https://acme.com/1")
    assert fp1 != fp2
    assert fp1 != fp3


def test_compute_application_fingerprint():
    candidate_id = "test-candidate"
    job_fp = "a" * 64
    app_fp1 = compute_application_fingerprint(candidate_id, job_fp)
    app_fp2 = compute_application_fingerprint(candidate_id, job_fp)
    app_fp3 = compute_application_fingerprint("other-candidate", job_fp)

    assert app_fp1 == app_fp2
    assert app_fp1 != app_fp3
    assert len(app_fp1) == 64
