"""DB'deki son N eslesmis ilani etiketleme sablonuna aktarir (task1 GOREV 2).

AJAN ETIKET UYDURMAZ: `label` her satirda null gelir, kullanici elle
doldurur (QUALIFIED | REVIEW | NOT_QUALIFIED). Skor/band yalnizca
baglam icindir. Cikti tests/golden/real_labeled.jsonl (gitignore'da).

Kullanim (DB'ye erisim icin compose agi icinden; dosya dogrudan host'a yazilir):
    docker compose run --rm -v ./tests/golden:/out orchestrator python scripts/export_for_labeling.py 40 /out/real_labeled.jsonl
    make export-labels
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main(limit: int = 40, out: str = "tests/golden/real_labeled.jsonl") -> None:
    from sqlalchemy import desc, select

    from shared.db.models import Job, JobMatch
    from shared.db.session import async_session_maker

    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(Job, JobMatch)
                .join(JobMatch, JobMatch.job_id == Job.id)
                .order_by(desc(JobMatch.scored_at))
                .limit(limit)
            )
        ).all()
    with Path(out).open("w", encoding="utf-8") as f:
        for job, match in rows:
            f.write(
                json.dumps(
                    {
                        "id": f"db-{str(job.id)[:8]}",
                        "title": job.title,
                        "company": job.company,
                        "description": job.description or "",
                        "requirements": list(job.requirements or []),
                        "location": job.location,
                        "remote_status": job.remote_status,
                        "url": job.url,
                        "model_score": float(match.overall_score),
                        "model_band": match.qualification_status,
                        "label": None,  # QUALIFIED | REVIEW | NOT_QUALIFIED (kullanici doldurur)
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"wrote {len(rows)} rows -> {out}")  # noqa: T201 - CLI


if __name__ == "__main__":
    args = [int(a) if a.isdigit() else a for a in sys.argv[1:]]
    asyncio.run(main(*args))
