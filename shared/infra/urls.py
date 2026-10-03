"""SSRF guard for user-supplied URLs (manual posting intake, analyzer fetch).

Blocks what can be proven bad without DNS resolution: non-http(s) schemes,
missing hosts, and literal non-public IP addresses (loopback, private,
link-local incl. the 169.254.169.254 metadata address, multicast, reserved,
unspecified). Hostnames are NOT resolved here on purpose: resolution would
make offline tests and local development depend on DNS. Documented residual
risk: DNS rebinding of an attacker-controlled hostname (accepted for the
single-user local tool threat model; see yama.md Faz 2-D).
"""
import ipaddress
from urllib.parse import urlparse

# Hostnames that are never public, blocked without DNS resolution.
_BLOCKED_HOST_EXACT = {"localhost", "metadata.google.internal"}
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".localdomain")


def assert_public_http_url(url: str) -> str:
    """Validates a user-supplied URL, returning the stripped URL.

    Raises ValueError for anything that is not plausibly a public http(s) URL.
    """
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be an absolute http(s) URL with a host.")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOST_EXACT or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError(f"Non-public host blocked: {parsed.hostname}")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return cleaned  # hostname: no DNS here by design (see module docstring)
    if not ip.is_global:
        raise ValueError(f"Non-public address blocked: {parsed.hostname}")
    return cleaned
