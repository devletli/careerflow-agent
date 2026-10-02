"""Hard-stop regression tests: CAPTCHA / login wall / MFA fixtures.

Served over local HTTP (form_server fixture). No internet access, no real
sites, no real applications.
"""
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("page_name,expected", [
    ("captcha.html", "CAPTCHA"),
    ("login_wall.html", "LOGIN"),
    ("mfa.html", "MFA"),
])
async def test_hard_stop_on_blockers(engine, form_server, page_name, expected):
    result = await engine.run(f"{form_server}/{page_name}", plan=[])
    assert result.blocked_reason == expected
    assert result.submitted is False
