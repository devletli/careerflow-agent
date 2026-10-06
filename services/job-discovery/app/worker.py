import argparse
import asyncio
import logging
import math
import signal
import time
from uuid import uuid4

from shared.config import settings
from shared.contracts.events import DiscoverySummaryEvent, JobDiscoveredEvent, JobNormalizedEvent
from shared.contracts.models import PipelineStatus
from shared.db.models import Job, utc_now
from shared.db.session import get_session, check_db_health
from shared.infra.redis_bus import RedisEventBus
from shared.infra.heartbeat import beat
from shared.infra.jsonlog import correlation, install_json_logging
from shared.profile.loader import load_canonical_profile
from browser.site_adapters.discovery.prefilter import passes_prefilter
from browser.site_adapters.discovery import (
    WorkableAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    AshbyAdapter,
    SmartRecruitersAdapter,
    BundesagenturAdapter,
    ArbeitnowAdapter,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("job-discovery")
CONTROL_GROUP = "job-discovery-control-group"
CONTROL_CONSUMER = f"discovery-control-{uuid4().hex[:6]}"


async def find_existing_job(session, source: str, source_job_id: str, job_fingerprint: str = None):
    """Checks whether a job already exists by (source, source_job_id) or by job_fingerprint."""
    from sqlalchemy import select, or_
    conditions = [
        (Job.source == source) & (Job.source_job_id == source_job_id)
    ]
    if job_fingerprint:
        conditions.append(Job.job_fingerprint == job_fingerprint)
    stmt = select(Job).where(or_(*conditions))
    result = await session.execute(stmt)
    return result.scalars().first()


class JobDiscoveryWorker:
    def __init__(self):
        self.bus = RedisEventBus()
        self.profile = load_canonical_profile()
        candidates = [
            BundesagenturAdapter(),
            ArbeitnowAdapter(),
            WorkableAdapter(),
            GreenhouseAdapter(),
            LeverAdapter(),
            AshbyAdapter(),
            SmartRecruitersAdapter(),
        ]
        self.adapters = []
        for adapter in candidates:
            flag = f"{adapter.source_name.upper()}_ENABLED"
            enabled = getattr(settings, flag, True)
            if enabled:
                self.adapters.append(adapter)
            else:
                logger.info("Discovery adapter disabled by %s: %s", flag, adapter.source_name)
        logger.info(
            "Active discovery adapters: %s",
            [a.source_name for a in self.adapters],
        )
        self.running = False

    async def run_discovery_cycle(self) -> int:
        """Runs a single pass of job discovery across all configured sources."""
        logger.info("Starting job discovery cycle...")
        started = time.monotonic()
        deadline = started + settings.DISCOVERY_TIME_BUDGET_SECONDS
        total_new = 0
        sources: dict = {}

        preferred_roles = self.profile.preferences.get("preferred_roles", ["AI Engineer", "DevOps"])
        roles = preferred_roles[:3]
        # First configured location (e.g. "Berlin"); adapters without location support ignore it.
        locations = self.profile.preferences.get("locations") or []
        location = locations[0] if locations else None
        per_role_limit = max(1, math.ceil(settings.DISCOVERY_MAX_JOBS_PER_SOURCE / max(1, len(roles))))
        prefs = self.profile.preferences
        budget_exceeded = False

        for adapter in self.adapters:
            logger.info(f"Running discovery with adapter: {adapter.source_name}")
            stats = {"found": 0, "prefiltered_out": 0, "new": 0, "duplicates": 0}
            src_started = time.monotonic()
            try:
                for role in roles:  # query top preferred roles
                    if time.monotonic() > deadline:
                        budget_exceeded = True
                        break
                    jobs = await adapter.discover_jobs(
                        query=role,
                        location=location,
                        limit=per_role_limit,
                        max_pages=settings.DISCOVERY_MAX_PAGES_PER_SOURCE,
                        page_delay=settings.DISCOVERY_PAGE_DELAY_SECONDS,
                        deadline=deadline,
                    )
                    for job_model in jobs:
                        if time.monotonic() > deadline:
                            budget_exceeded = True
                            break
                        stats["found"] += 1
                        passed, reason = passes_prefilter(
                            title=job_model.title,
                            location=job_model.location,
                            remote_status=job_model.remote_status,
                            text=f"{job_model.description or ''} {job_model.company or ''}",
                            preferences=prefs,
                        )
                        if not passed:
                            stats["prefiltered_out"] += 1
                            logger.debug(
                                "Prefiltered out %s - %s (%s): %s",
                                job_model.company, job_model.title, job_model.source, reason,
                            )
                            continue
                        is_new = await self._persist_and_emit(job_model)
                        if is_new:
                            stats["new"] += 1
                            total_new += 1
                        else:
                            stats["duplicates"] += 1

            except Exception as e:
                logger.error(f"Error in adapter {adapter.source_name}: {e}", exc_info=True)

            stats["duration_s"] = round(time.monotonic() - src_started, 1)
            sources[adapter.source_name] = stats

        duration_s = round(time.monotonic() - started, 1)
        if time.monotonic() > deadline:
            budget_exceeded = True
        stale_count = await self.mark_stale_jobs()
        summary = DiscoverySummaryEvent(
            correlation_id=f"disc-{uuid4().hex[:8]}",
            entity_id="discovery",
            payload={
                "sources": sources,
                "total_new": total_new,
                "stale_marked": stale_count,
                "duration_s": duration_s,
                "budget_exceeded": budget_exceeded,
                "budgets": {
                    "max_jobs_per_source": settings.DISCOVERY_MAX_JOBS_PER_SOURCE,
                    "max_pages_per_source": settings.DISCOVERY_MAX_PAGES_PER_SOURCE,
                    "time_budget_s": settings.DISCOVERY_TIME_BUDGET_SECONDS,
                },
            },
        )
        try:
            await self.bus.publish(summary)
        except Exception as e:
            logger.warning("Discovery summary publish failed: %s", e)
        logger.info(
            "Discovery cycle complete. New %d in %.1fs (budget_exceeded=%s): %s",
            total_new, duration_s, budget_exceeded,
            {k: (v["found"], v["new"]) for k, v in sources.items()},
        )
        return total_new

    async def _persist_and_emit(self, job_model) -> bool:
        """Checks duplicate and persists new job, emitting discovery events."""
        async with get_session() as session:
            existing = await find_existing_job(
                session,
                job_model.source,
                job_model.source_job_id,
                job_model.job_fingerprint,
            )
            if existing is not None:
                existing.last_seen_at = utc_now()  # Faz 3: STALE sweep için görüşü tazele
                return False  # Already known, incremental skip

            job_id = uuid4()
            job = Job(
                id=job_id,
                source=job_model.source,
                source_job_id=job_model.source_job_id,
                company=job_model.company,
                title=job_model.title,
                url=job_model.url,
                application_url=job_model.application_url,
                location=job_model.location,
                remote_status=job_model.remote_status,
                description=job_model.description,
                requirements=job_model.requirements,
                publication_metadata=job_model.publication_metadata,
                job_fingerprint=job_model.job_fingerprint,
                status=PipelineStatus.NORMALIZED.value,
                last_seen_at=utc_now(),
                raw_data=job_model.raw_data,
            )
            session.add(job)

        # Emit events via Redis
        correlation_id = f"disc-{uuid4().hex[:8]}"
        discovered_ev = JobDiscoveredEvent(
            correlation_id=correlation_id,
            entity_id=str(job_id),
            payload={
                "source": job_model.source,
                "source_job_id": job_model.source_job_id,
                "company": job_model.company,
                "title": job_model.title,
                "url": job_model.url,
                "application_url": job_model.application_url,
                "location": job_model.location,
                "remote_status": job_model.remote_status,
            },
        )
        normalized_ev = JobNormalizedEvent(
            correlation_id=correlation_id,
            entity_id=str(job_id),
            payload={
                "job_fingerprint": job_model.job_fingerprint,
                "company": job_model.company,
                "title": job_model.title,
            },
        )
        await self.bus.publish(discovered_ev)
        await self.bus.publish(normalized_ev)
        logger.info(f"Ingested new job: {job_model.company} - {job_model.title} ({job_id})")
        return True

    async def mark_stale_jobs(self) -> int:
        """Marks jobs unseen for JOBS_STALE_AFTER_DAYS as STALE (kept, hidden).

        Faz 3: history preserved, default listing hides them.
        """
        from datetime import timedelta

        cutoff = utc_now() - timedelta(days=settings.JOBS_STALE_AFTER_DAYS)
        async with get_session() as session:
            from sqlalchemy import select

            stmt = select(Job).where(
                Job.last_seen_at.is_not(None),
                Job.last_seen_at < cutoff,
                Job.status != "STALE",
            )
            rows = (await session.execute(stmt)).scalars().all()
            for job in rows:
                job.status = "STALE"
            if rows:
                logger.info("Marked %d jobs STALE (unseen since %s)", len(rows), cutoff.date())
            return len(rows)

    async def start(self, once: bool = False, interval_seconds: int = 3600):
        self.running = True
        if settings.LOG_FORMAT == "json":
            install_json_logging()
        logger.info(f"Job discovery service initialized (once={once}, interval={interval_seconds}s)")

        # Wait for DB and Redis to be ready
        for _ in range(15):
            if await check_db_health() and await self.bus.ping():
                break
            await asyncio.sleep(2)

        await self.run_discovery_cycle()
        if once:
            return

        next_scheduled_run = time.monotonic() + interval_seconds
        while self.running:
            # Gorev 7: her turda heartbeat (mesaj olsun olmasin).
            await beat(await self.bus.get_redis(), "job-discovery")
            wait_ms = max(
                1,
                min(int((next_scheduled_run - time.monotonic()) * 1000), 10_000),
            )
            # T5: reprocess idle pending messages left by crashed workers.
            reclaimed = await self.bus.reclaim_events(
                stream=settings.STREAM_EVENTS,
                group=CONTROL_GROUP,
                consumer=CONTROL_CONSUMER,
            )
            events = reclaimed + await self.bus.read_events(
                stream=settings.STREAM_EVENTS,
                group=CONTROL_GROUP,
                consumer=CONTROL_CONSUMER,
                count=10,
                block_ms=wait_ms,
            )
            for message_id, event in events:
                # Faz 4A: JSON loglara correlation_id islenir.
                with correlation(event.correlation_id, event.entity_id):
                    if (
                        event.event_type == "pipeline.control.v1"
                        and event.payload.get("action") == "discover"
                    ):
                        logger.info("Received manual discovery request correlation_id=%s", event.correlation_id)
                        await self.run_discovery_cycle()
                    await self.bus.ack(settings.STREAM_EVENTS, CONTROL_GROUP, message_id)
            if time.monotonic() >= next_scheduled_run:
                await self.run_discovery_cycle()
                next_scheduled_run = time.monotonic() + interval_seconds

    async def stop(self):
        self.running = False
        await self.bus.close()


async def main():
    parser = argparse.ArgumentParser(description="Job Discovery Worker")
    parser.add_argument("--once", action="store_true", help="Run a single discovery cycle and exit")
    parser.add_argument("--interval", type=int, default=3600, help="Interval between discovery cycles in seconds")
    args = parser.parse_args()

    worker = JobDiscoveryWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    try:
        await worker.start(once=args.once, interval_seconds=args.interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
