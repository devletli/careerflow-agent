"""Faz 6: 5000 ilanla rank sorgusu performans dogrulamasi (SQLite, offline).

Kullanim: python scripts/perf_jobs_rank.py
Rapor: EXPLAIN QUERY PLAN (ix_job_matches_rank kullanimi) + ilk sayfa suresi.
"""
import asyncio
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from shared.db.models import Base, Job, JobMatch  # noqa: E402


async def main(n: int = 5000) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as s:
        for i in range(n):
            job = Job(
                id=uuid4(), source="perf", source_job_id=f"p-{i}",
                company=f"C{i % 100}", title=f"Engineer {i}",
                url=f"https://perf.example/{i}", job_fingerprint=f"pfp-{i}",
                status="NORMALIZED",
            )
            s.add(job)
            await s.flush()
            if i % 5 != 0:  # %80 scored
                s.add(JobMatch(
                    job_id=job.id, overall_score=float((i * 37) % 100),
                    confidence=0.9, qualification_status="REVIEW",
                ))
        await s.commit()

        from sqlalchemy import text as sa_text

        idx_rows = (await s.execute(sa_text("SELECT name, tbl_name FROM sqlite_master WHERE type='index'"))).all()
        print("indexes:", sorted(f"{t}.{n_}" for n_, t in idx_rows))  # noqa: T201 - CLI raporu

        score_col = func.coalesce(JobMatch.overall_score, -1)
        stmt = (
            select(Job, JobMatch.overall_score)
            .outerjoin(JobMatch, JobMatch.job_id == Job.id)
            .where(Job.status != "STALE")
            .order_by(score_col.desc(), Job.id)
            .limit(101)
        )
        compiled = stmt.compile(engine, compile_kwargs={"literal_binds": True})
        plan = (await s.execute(sa_text(f"EXPLAIN QUERY PLAN {compiled}"))).all()
        print("plan:")  # noqa: T201 - CLI raporu
        for row in plan:
            print("  ", tuple(row)[-1])  # noqa: T201 - CLI raporu

        t0 = time.perf_counter()
        rows = (await s.execute(stmt)).all()
        dt_ms = (time.perf_counter() - t0) * 1000
        scores = [r[1] if r[1] is not None else -1 for r in rows[:100]]
        ordered = all(a >= b for a, b in zip(scores, scores[1:]))
        print(f"rows={len(rows[:100])} ordered={ordered} time_ms={dt_ms:.1f} target_lt_300ms={dt_ms < 300}")  # noqa: T201 - CLI raporu
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
