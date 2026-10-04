import argparse
import asyncio
import logging
import signal
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import select

from shared.config import settings
from shared.contracts.events import JobMatchedEvent, JobQualifiedEvent
from shared.contracts.models import PipelineStatus
from shared.db.models import Job, JobMatch
from shared.db.session import get_session, check_db_health
from shared.infra.redis_bus import RedisEventBus
from shared.infra.heartbeat import beat
from shared.infra.jsonlog import correlation
from shared.profile.loader import load_canonical_profile
from app.matcher import JobMatchingEngine

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("job-matching")

CONSUMER_GROUP = "matching-group"
CONSUMER_NAME = f"matching-worker-{uuid4().hex[:6]}"


class JobMatchingWorker:
    def __init__(self):
        self.bus = RedisEventBus()
        self.profile = load_canonical_profile()
        self.engine = JobMatchingEngine()
        self.running = False

    async def match_job(self, job_id: UUID) -> Optional[JobMatch]:
        """Loads job from DB, runs matching engine, and saves match result."""
        async with get_session() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalars().first()
            if not job:
                logger.warning(f"Job {job_id} not found in database for matching")
                return None

            match_result = self.engine.evaluate_match(
                job_id=job.id,
                title=job.title,
                description=job.description or "",
                requirements=job.requirements or [],
                location=job.location,
                remote_status=job.remote_status,
                profile=self.profile,
                min_threshold=settings.MIN_MATCH_SCORE,
            )
            if match_result.qualification.value in ("QUALIFIED", "REVIEW"):
                match_result = await self.engine.add_llm_explanation(
                    result=match_result,
                    title=job.title,
                    description=job.description or "",
                    profile=self.profile,
                )

            # Check existing match or insert new
            stmt_m = select(JobMatch).where(JobMatch.job_id == job.id)
            res_m = await session.execute(stmt_m)
            existing_match = res_m.scalars().first()

            if existing_match:
                match_record = existing_match
                match_record.overall_score = match_result.overall_score
                match_record.confidence = match_result.confidence
                match_record.qualification_status = match_result.qualification.value
                match_record.component_scores = match_result.component_scores
                match_record.hard_requirements = match_result.hard_requirements
                match_record.matching_skills = match_result.matching_skills
                match_record.missing_skills = match_result.missing_skills
                match_record.explanation = match_result.explanation
            else:
                match_record = JobMatch(
                    job_id=job.id,
                    overall_score=match_result.overall_score,
                    confidence=match_result.confidence,
                    qualification_status=match_result.qualification.value,
                    component_scores=match_result.component_scores,
                    hard_requirements=match_result.hard_requirements,
                    matching_skills=match_result.matching_skills,
                    missing_skills=match_result.missing_skills,
                    explanation=match_result.explanation,
                )
                session.add(match_record)

            # Update job status
            if match_result.qualification.value == "QUALIFIED":
                job.status = PipelineStatus.QUALIFIED.value
            else:
                job.status = PipelineStatus.MATCHED.value

        # Emit events
        correlation_id = f"match-{uuid4().hex[:8]}"
        matched_ev = JobMatchedEvent(
            correlation_id=correlation_id,
            entity_id=str(job_id),
            payload={
                "overall_score": match_result.overall_score,
                "qualification": match_result.qualification.value,
                "confidence": match_result.confidence,
            },
        )
        await self.bus.publish(matched_ev)

        if match_result.qualification.value == "QUALIFIED":
            qualified_ev = JobQualifiedEvent(
                correlation_id=correlation_id,
                entity_id=str(job_id),
                payload={
                    "overall_score": match_result.overall_score,
                    "confidence": match_result.confidence,
                },
            )
            await self.bus.publish(qualified_ev)
            logger.info(f"Job {job_id} QUALIFIED with score {match_result.overall_score}%")
        else:
            logger.info(f"Job {job_id} MATCHED with score {match_result.overall_score}% ({match_result.qualification.value})")

        return match_record

    async def match_all_unmatched(self, include_matched: bool = False) -> int:
        """Evaluates normalized jobs, or all non-terminal jobs when requested."""
        count = 0
        async with get_session() as session:
            if include_matched:
                stmt = select(Job.id).where(
                    Job.status.notin_(
                        [
                            PipelineStatus.SUBMITTED.value,
                            PipelineStatus.VERIFIED.value,
                            PipelineStatus.FAILED.value,
                            PipelineStatus.BLOCKED.value,
                        ]
                    )
                )
            else:
                stmt = select(Job.id).where(Job.status == PipelineStatus.NORMALIZED.value)
            res = await session.execute(stmt)
            job_ids = res.scalars().all()

        for j_id in job_ids:
            await self.match_job(j_id)
            count += 1
        return count

    async def start(self, once: bool = False):
        self.running = True
        logger.info("Job matching worker started")

        for _ in range(15):
            if await check_db_health() and await self.bus.ping():
                break
            await asyncio.sleep(2)

        await self.bus.ensure_consumer_group(settings.STREAM_EVENTS, CONSUMER_GROUP)

        # Faz 1C: LLM modelini acilista dogrula; gecersizse deterministik devam.
        from shared.llm.models import validate_llm_at_startup

        await validate_llm_at_startup()

        # Initial sweep of existing unmatched jobs
        await self.match_all_unmatched()
        if once:
            return

        while self.running:
            try:
                # Gorev 7: her turda heartbeat (mesaj olsun olmasin).
                await beat(await self.bus.get_redis(), "job-matching")
                # T5: reprocess idle pending messages left by crashed workers.
                reclaimed = await self.bus.reclaim_events(
                    stream=settings.STREAM_EVENTS,
                    group=CONSUMER_GROUP,
                    consumer=CONSUMER_NAME,
                )
                events = reclaimed + await self.bus.read_events(
                    stream=settings.STREAM_EVENTS,
                    group=CONSUMER_GROUP,
                    consumer=CONSUMER_NAME,
                    count=5,
                    block_ms=2000,
                )
                for msg_id, event in events:
                    # Faz 4A: JSON loglara correlation_id islenir.
                    with correlation(event.correlation_id, event.entity_id):
                        if (
                            event.event_type == "pipeline.control.v1"
                            and event.payload.get("action") == "match"
                        ):
                            logger.info("Received manual matching request correlation_id=%s", event.correlation_id)
                            await self.match_all_unmatched(include_matched=True)
                        elif event.event_type in ("job.normalized.v1", "job.discovered.v1"):
                            try:
                                job_id = UUID(event.entity_id)
                                await self.match_job(job_id)
                            except Exception as e:
                                logger.error(f"Error matching job {event.entity_id}: {e}", exc_info=True)
                        await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in matching loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def stop(self):
        self.running = False
        await self.bus.close()


async def main():
    parser = argparse.ArgumentParser(description="Job Matching Worker")
    parser.add_argument("--once", action="store_true", help="Match all unmatched jobs once and exit")
    args = parser.parse_args()

    worker = JobMatchingWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    try:
        await worker.start(once=args.once)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
