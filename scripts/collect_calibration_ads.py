"""Gercek ilanlari toplayip etiket sablonu yazar (B5 yardimcisi).

AJAN etiketlemez: bu script yalnizca herkese acik is ilanlarini ceker ve
tests/golden/real_labeled.jsonl dosyasina BOS etiketle yazar. Hukum
(QUALIFIED / REVIEW / NOT_QUALIFIED) kullaniciya aittir: her satirdaki
"label": "" alanini doldurmasi yeter, ilan bulma/yazma isi kalkar.

Kullanim:
    python scripts/collect_calibration_ads.py [--limit 30] [--append]
    make collect-calibration
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET = ROOT / "tests" / "golden" / "real_labeled.jsonl"
LABELS = ("QUALIFIED", "REVIEW", "NOT_QUALIFIED")


def _row(job, seq: int) -> dict:
    return {
        "id": f"real-{seq:02d}",
        "source": job.source,
        "title": job.title or "",
        "company": job.company or "",
        "description": (job.description or "")[:4000],
        "requirements": list(job.requirements or [])[:20],
        "location": job.location,
        "remote_status": job.remote_status,
        "url": job.url,
        "label": "",
    }


async def _collect(limit: int) -> list:
    from browser.site_adapters.discovery.arbeitnow import ArbeitnowAdapter
    from shared.profile.loader import load_canonical_profile

    profile = load_canonical_profile()
    roles = profile.preferences.get("preferred_roles", ["Engineer"]) or ["Engineer"]
    locations = profile.preferences.get("locations") or []
    location = locations[0] if locations else None
    adapter = ArbeitnowAdapter()
    seen, rows = set(), []
    for role in roles[:3]:
        for job in await adapter.discover_jobs(query=role, location=location, limit=limit):
            key = (job.source, job.source_job_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(job)
            if len(rows) >= limit:
                return rows
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--append", action="store_true", help="varsa dosyaya ekle")
    args = parser.parse_args(argv)

    if TARGET.exists() and not args.append:
        print(f"{TARGET} zaten var; uzerine yazmamak icin --append kullan")  # noqa: T201 - CLI
        return 2
    existing = []
    if TARGET.exists():
        for line in TARGET.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.append(json.loads(line))
    have = {(r.get("source"), r.get("title"), r.get("company")) for r in existing}

    jobs = asyncio.run(_collect(args.limit + len(existing)))
    fresh = [j for j in jobs if (j.source, j.title, j.company) not in have][: args.limit]
    seq = len(existing) + 1
    with TARGET.open("a" if args.append else "w", encoding="utf-8") as f:
        for job in fresh:
            f.write(json.dumps(_row(job, seq), ensure_ascii=False) + "\n")
            seq += 1
    print(f"{len(fresh)} ilan yazildi -> {TARGET}")  # noqa: T201 - CLI
    print('sonraki adim: her satirdaki "label": "" alanini doldur (QUALIFIED / REVIEW / NOT_QUALIFIED)')  # noqa: T201 - CLI
    return 0


if __name__ == "__main__":
    sys.exit(main())
