"""Compose healthcheck probe for workers (Gorev 7).

Kullanim (compose healthcheck): python /app/scripts/healthcheck_worker.py <service>
Cikis 0 = 30sn icinde heartbeat goruldu; 1 = yok (unhealthy).
"""
import os
import sys

import redis


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("usage: healthcheck_worker.py <service>", file=sys.stderr)  # noqa: T201 - CLI
        return 1
    service = sys.argv[1].strip()
    url = os.getenv("REDIS_URL") or "redis://redis:6379/0"
    try:
        r = redis.Redis.from_url(url, socket_timeout=2)
        return 0 if r.exists(f"hb:{service}") else 1
    except Exception as exc:  # fail-closed: supheli durum unhealthy'dir
        print(f"heartbeat probe failed: {exc}", file=sys.stderr)  # noqa: T201 - CLI
        return 1


if __name__ == "__main__":
    sys.exit(main())
