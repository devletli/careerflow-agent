"""ATS resolution from URLs + live pages (stdlib only, no engine import).

Merkezi ATS bilgisi: sonek eslesmesi (ats_stats.py buradan beslenir,
Faz 3 adapter secimi de buraya baglanir). Headless engine.py'ye
dokunulmaz; bu modul yalnizca okur (tiklama/submit yok).
"""
from __future__ import annotations

from urllib.parse import urlparse

# Sonek eslesmesi; alt alan adlari eslesir, benzer ama farkli hostlar
# (evilgreenhouse.io) eslesmez. Liste ats_stats verisine gore genisletilir.
ATS_HOSTS = {
    "greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "workable.com": "workable",
    "apply.workable.com": "workable",
    "ashbyhq.com": "ashby",
    "jobs.ashbyhq.com": "ashby",
    "smartrecruiters.com": "smartrecruiters",
    "personio.de": "personio",
    "personio.com": "personio",
    "join.com": "join",
    "softgarden.de": "softgarden",
    "softgarden.io": "softgarden",
    "recruitee.com": "recruitee",
}


def host_of(url: str) -> str:
    try:
        return (urlparse((url or "").strip()).hostname or "").lower()
    except Exception:
        return ""


def ats_from_host(host: str) -> str | None:
    host = (host or "").lower().strip()
    for suffix, name in ATS_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return None


def ats_from_url(url: str) -> str | None:
    """URL -> ATS adi; eslesme yoksa None (cagri 'generic' varsayar)."""
    return ats_from_host(host_of(url))


async def detect_ats(page) -> str:
    """Sayfa + tum framelerin URL'lerinden ATS'yi algila (gomulu formlar
    iframe'de olabilir). Yonlendirme sonrasi son URL page.url'dir."""
    urls: list[str] = []
    try:
        urls.append(page.url)
    except Exception:
        pass
    try:
        frames = page.frames
    except Exception:
        frames = []
    for frame in frames or []:
        try:
            urls.append(frame.url)
        except Exception:
            continue
    for url in urls:
        name = ats_from_url(url)
        if name:
            return name
    return "generic"
