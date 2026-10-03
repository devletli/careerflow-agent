"""Faz 2-D: SSRF guard unit tests (offline, no DNS)."""
import pytest

from shared.infra.urls import assert_public_http_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/jobs/42",
        "http://example.com/apply?x=1",
        "https://karriere.example.com/42",
        "  https://example.com/jobs/42  ",
    ],
)
def test_public_urls_pass(url):
    assert assert_public_http_url(url).startswith("http")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "not-a-url",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "http://",
        "http://127.0.0.1:8000/api/v1/status",
        "http://localhost:3000/",
        "http://10.0.0.5/apply",
        "http://192.168.1.20/jobs",
        "http://172.16.9.9/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://0.0.0.0:8000/",
    ],
)
def test_non_public_urls_rejected(url):
    with pytest.raises(ValueError):
        assert_public_http_url(url)
