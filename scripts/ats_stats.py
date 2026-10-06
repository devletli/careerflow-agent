"""DB'deki ilanlarin basvuru URL host dagilimi + ATS tahmini.

Cikti ("hangi ATS kac ilan" tablosu) adapter yazma onceligini belirler.
Kullanim:
    python scripts/ats_stats.py [--limit 5000] [--top 20]
    python scripts/ats_stats.py --from-file urls.txt
    python scripts/ats_stats.py --dsn postgresql://... [--limit 5000]

Not: ATS sonek eslesmesi Faz 2'de browser/site_adapters/resolve.py'da
merkezilesir; burada kucuk bir kopya vardir (Faz 2 bunu tekilleyecek).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Tek kaynak: browser/site_adapters/resolve.py (import edilemezse kucuk kopya).
try:
    from browser.site_adapters.resolve import (  # noqa: E402
        ATS_HOSTS,
        ats_from_host,
        ats_from_url,
        host_of,
    )
except Exception:  # pragma: no cover - yalnizca bozuk kurulumlarda
    ATS_HOSTS = {
        "greenhouse.io": "greenhouse",
        "lever.co": "lever",
        "workable.com": "workable",
        "ashbyhq.com": "ashby",
        "smartrecruiters.com": "smartrecruiters",
        "personio.de": "personio",
        "personio.com": "personio",
        "join.com": "join",
        "softgarden.de": "softgarden",
        "softgarden.io": "softgarden",
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
        return ats_from_host(host_of(url))


def count_hosts(urls: list[str]) -> Counter:
    counter: Counter = Counter()
    for url in urls:
        host = host_of(url)
        if host:
            counter[host] += 1
    return counter


def summarize(urls: list[str]) -> list[tuple[str, int, str]]:
    """(host, count, ats) satirlari, sayiya gore azalan."""
    counts = count_hosts(urls)
    rows = [
        (host, count, ats_from_host(host) or "unknown")
        for host, count in counts.items()
    ]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows


def print_table(rows: list[tuple[str, int, str]], *, top: int = 20) -> None:
    print(f"{'count':>7}  {'host':<45} ats")  # noqa: T201 - CLI
    print("-" * 70)  # noqa: T201 - CLI
    for host, count, ats in rows[:top]:
        print(f"{count:>7}  {host:<45} {ats}")  # noqa: T201 - CLI
    unknown = sum(c for _, c, a in rows if a == "unknown")
    total = sum(c for _, c, _ in rows)
    print("-" * 70)  # noqa: T201 - CLI
    print(f"toplam ilan: {total}, bilinmeyen ATS: {unknown}")  # noqa: T201 - CLI


async def fetch_urls_from_db(dsn: str, limit: int) -> list[str]:
    from sqlalchemy import text

    from sqlalchemy.ext.asyncio import create_async_engine

    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(dsn, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COALESCE(application_url, url) AS u "
                    "FROM jobs WHERE COALESCE(application_url, url) IS NOT NULL "
                    "LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [row[0] for row in result.fetchall() if row[0]]
    finally:
        await engine.dispose()


def load_urls_from_file(path: str) -> list[str]:
    urls: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Basvuru URL host/ATS dagilimi")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--from-file", default="",
                        help="DB yerine dosya (satir basina URL)")
    args = parser.parse_args(argv)

    if args.from_file:
        urls = load_urls_from_file(args.from_file)
    elif args.dsn:
        try:
            urls = asyncio.run(fetch_urls_from_db(args.dsn, args.limit))
        except Exception as exc:
            print(f"DB okunamadi: {exc}")  # noqa: T201 - CLI
            return 2
    else:
        print("DATABASE_URL yok: --dsn ya da --from-file gerekli")  # noqa: T201 - CLI
        return 2
    if not urls:
        print("URL bulunamadi.")  # noqa: T201 - CLI
        return 1
    print_table(summarize(urls), top=args.top)  # noqa: T201 - CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
