"""Worker heartbeat for compose healthchecks (Gorev 7).

Her worker ana dongude (mesaj olsun olmasin) beat() cagirir; probe
TTL dolmadan anahtari goremezse sagliksiz sayar. Bos ama saglikli
worker "unhealthy" olmaz, takilmis worker 30sn icinde yakalanir.
"""
import time

HB_PREFIX = "hb:"
HB_TTL_SECONDS = 30


async def beat(r, service: str, ttl: int = HB_TTL_SECONDS) -> None:
    await r.set(f"{HB_PREFIX}{service}", int(time.time()), ex=ttl)
