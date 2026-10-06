"""Application-target resolution (stdlib + playwright only).

Toplayici ilan sayfalari (bundesagentur, arbeitnow, manual) dogrudan form
degil ilan sayfasidir: sayfadaki basvuru baglantisi bulunur, gidilir,
yonlendirme sonrasi son URL'den ATS algilanir.

Kurallar:
- Yalnizca <a href> baglantilari takip edilir (GET navigasyonu; form
  verisi gonderilmez). Submit etiketli <button>'lara asla dokunulmaz.
- mailto tek secenekse durulur: REQUIRES_HUMAN reason=EMAIL_ONLY. Mail
  ATILMAZ; adres yalnizca panele gosterilir (report.json'a yazilmaz).
- Cevrimici form yoksa REQUIRES_HUMAN reason=NO_ONLINE_FORM.
- Blocker'li (CAPTCHA/login/MFA) veya form/opener'li sayfalarda "stay":
  karar donguye (handoff/opener) birakilir.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse

from desktop_runner.navigation import FORM_OPENER_RX, is_submit_label, wait_for_content

APPLY_LINK_RX = re.compile(
    r"bewerb|apply|kandidatur|candidatura|sollicit|ba.l?vur|postuler",
    re.I,
)

MAX_ANCHORS = 200
MAX_NAV_ATTEMPTS = 3


def _central_ats_from_url(url: str):
    """Merkezi tablo (browser.site_adapters.resolve); yoksa None."""
    try:
        from browser.site_adapters.resolve import ats_from_url

        return ats_from_url(url)
    except Exception:
        return None


def ats_name_for_url(url: str) -> str:
    return _central_ats_from_url(url) or "generic"


async def page_ats(page) -> str:
    """Sayfa + framelerin URL'lerinden ATS (gomulu formlar icin)."""
    urls: list[str] = []
    try:
        urls.append(page.url)
    except Exception:
        pass
    try:
        frames = page.frames or []
    except Exception:
        frames = []
    for frame in frames:
        try:
            urls.append(frame.url)
        except Exception:
            continue
    for url in urls:
        if ats_name_for_url(url) != "generic":
            return ats_name_for_url(url)
    return "generic"


async def has_form_opener(page) -> bool:
    """Tiklamadan bakar: formu acan dugme var mi (posting sayfasi ipucu)."""
    try:
        buttons = await page.get_by_role("button").all()
    except Exception:
        return False
    for btn in buttons:
        try:
            name = (await btn.inner_text()).strip()
        except Exception:
            continue
        if not name or is_submit_label(name):
            continue
        try:
            if FORM_OPENER_RX.match(name) and await btn.is_visible():
                return True
        except Exception:
            continue
    return False


def mailto_address(href: str) -> str | None:
    """mailto:abc@x?subject=.. -> abc@x; gecersizse None. Mail ATILMAZ."""
    try:
        parsed = urlparse((href or "").strip())
    except Exception:
        return None
    if parsed.scheme.lower() != "mailto":
        return None
    addr = unquote(parsed.path or "").strip().rstrip(",;")
    if "@" not in addr or " " in addr:
        return None
    return addr


async def find_apply_links(page) -> tuple[list[str], list[str]]:
    """Gorunur basvuru baglantilari: (http_url'ler, mailto_adresleri)."""
    http_urls: list[str] = []
    emails: list[str] = []
    try:
        anchors = page.locator("a[href]")
        total = min(await anchors.count(), MAX_ANCHORS)
    except Exception:
        return [], []
    try:
        base = page.url
    except Exception:
        base = ""
    for index in range(total):
        link = anchors.nth(index)
        try:
            if not await link.is_visible():
                continue
            href = (await link.get_attribute("href")) or ""
            text = (await link.inner_text()).strip()
        except Exception:
            continue
        if not href or href.startswith(("#", "javascript:")):
            continue
        email = mailto_address(href)
        if email:
            if email not in emails:
                emails.append(email)
            continue
        if not APPLY_LINK_RX.search(text):
            try:
                aria = (await link.get_attribute("aria-label")) or ""
            except Exception:
                aria = ""
            if not APPLY_LINK_RX.search(aria):
                continue
        absolute = urljoin(base, href)
        try:
            if urlparse(absolute).scheme not in ("http", "https"):
                continue
        except Exception:
            continue
        if absolute not in http_urls:
            http_urls.append(absolute)
    return http_urls, emails


async def resolve_target(page, app_url: str, *, form_like: bool,
                         blocked: bool, recheck_form) -> dict:
    """Hedefi coz. Donus: kind=form|stay|moved|email_only|no_form (+url,
    +ats, email_only'da +email, olumsuzda +reason). 'moved' teyitli
    form demektir (recheck_form ile dogrulandi)."""
    ats = await page_ats(page)
    if blocked or form_like:
        return {"kind": "form" if form_like else "stay",
                "url": page.url, "ats": ats}
    if await has_form_opener(page):
        return {"kind": "stay", "url": page.url, "ats": ats}
    http_urls, emails = await find_apply_links(page)
    for candidate in http_urls[:MAX_NAV_ATTEMPTS]:
        try:
            await page.goto(candidate, wait_until="domcontentloaded", timeout=45_000)
        except Exception:
            continue
        await wait_for_content(page)
        try:
            if await recheck_form(page):
                return {"kind": "moved", "url": page.url,
                        "ats": await page_ats(page)}
        except Exception:
            continue
    if emails and not http_urls:
        return {"kind": "email_only", "url": page.url,
                "ats": ats, "email": emails[0], "reason": "EMAIL_ONLY"}
    try:
        final_url = page.url
    except Exception:
        final_url = ""
    return {"kind": "no_form", "url": final_url,
            "ats": await page_ats(page), "reason": "NO_ONLINE_FORM"}
