import asyncio
import logging
import signal
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import select

from shared.config import settings
from shared.contracts.events import (
    BaseEvent,
    JobDiscoveredEvent,
    JobMatchedEvent,
    JobQualifiedEvent,
    DocumentsGeneratedEvent,
    ApplicationAnalyzedEvent,
    ApplicationSubmittedEvent,
    ApplicationFailedEvent,
    ApplicationBlockedEvent,
)
from shared.contracts.models import PipelineStatus, AutomationMode
from shared.contracts.fingerprint import (
    compute_job_fingerprint,
    compute_application_fingerprint,
)
from shared.db.models import (
    Job,
    JobMatch,
    Document,
    Application,
    PipelineEvent,
    DeadLetterEvent,
)
from shared.db.session import get_session, check_db_health
from shared.infra.redis_bus import RedisEventBus, calculate_backoff
from .state_machine import is_valid_transition, can_advance_mode
from .duplicate_detector import (
    find_existing_job,
    check_submission_eligibility,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")

CONSUMER_GROUP = "orchestrator-group"
CONSUMER_NAME = f"orchestrator-worker-{uuid4().hex[:6]}"
MAX_EVENT_RETRIES = 3


class OrchestratorWorker:
    def __init__(self):
        self.bus = RedisEventBus()
        self.running = False

    async def start(self):
        self.running = True
        logger.info(f"Orchestrator worker starting with mode={settings.AUTOMATION_MODE}")

        # Check DB and Redis connectivity
        db_ok = await check_db_health()
        redis_ok = await self.bus.ping()
        if not db_ok:
            logger.warning("Database connection is not healthy yet; will retry in loop")
        if not redis_ok:
            logger.warning("Redis connection is not healthy yet; will retry in loop")

        await self.bus.ensure_consumer_group(settings.STREAM_EVENTS, CONSUMER_GROUP)

        while self.running:
            try:
                events = await self.bus.read_events(
                    stream=settings.STREAM_EVENTS,
                    group=CONSUMER_GROUP,
                    consumer=CONSUMER_NAME,
                    count=10,
                    block_ms=2000,
                )

                for msg_id, event in events:
                    await self._process_with_retry(msg_id, event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in orchestrator loop: {e}", exc_info=True)
                await asyncio.sleep(2)

        logger.info("Orchestrator worker stopped cleanly")

    async def stop(self):
        self.running = False
        await self.bus.close()

    async def _process_with_retry(self, msg_id: str, event: BaseEvent):
        """Processes event with bounded retry backoff and dead-letter routing."""
        retry_count = int(event.payload.get("_retry_count", 0))

        try:
            # Check idempotency: if event_id already recorded in pipeline_events, skip
            async with get_session() as session:
                existing_ev = await session.execute(
                    select(PipelineEvent).where(PipelineEvent.event_id == UUID(event.event_id))
                )
                if existing_ev.scalars().first() is not None:
                    logger.debug(f"Event {event.event_id} already processed (idempotent skip)")
                    await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)
                    return

            # Process the event logic
            await self.handle_event(event)

            # Record in pipeline_events audit log
            async with get_session() as session:
                audit = PipelineEvent(
                    event_id=UUID(event.event_id),
                    event_type=event.event_type,
                    version=event.version,
                    correlation_id=event.correlation_id,
                    entity_id=event.entity_id,
                    entity_type="event",
                    payload=event.payload,
                    timestamp=datetime.fromisoformat(event.timestamp)
                    if isinstance(event.timestamp, str)
                    else datetime.now(timezone.utc),
                )
                session.add(audit)

            # Ack in Redis
            await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)

        except Exception as e:
            stack = traceback.format_exc()
            logger.error(
                f"Failed to process event {event.event_id} ({event.event_type}), retry={retry_count}: {e}"
            )

            if retry_count < MAX_EVENT_RETRIES:
                backoff = calculate_backoff(retry_count)
                logger.info(f"Will retry event {event.event_id} in {backoff:.1f}s")
                await asyncio.sleep(backoff)
                event.payload["_retry_count"] = retry_count + 1
                await self.bus.publish(event, settings.STREAM_EVENTS)
            else:
                logger.error(f"Max retries exceeded for event {event.event_id}. Routing to dead letter.")
                await self._route_dead_letter(event, str(e), stack, retry_count)

            # Always ack the current message so the consumer stream does not stall
            await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)

    async def _route_dead_letter(
        self,
        event: BaseEvent,
        error_msg: str,
        stack_trace: str,
        retries: int,
    ):
        """Records dead letter event to PostgreSQL and Redis DLQ."""
        try:
            async with get_session() as session:
                dl = DeadLetterEvent(
                    original_event_id=event.event_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    error_message=error_msg,
                    stack_trace=stack_trace,
                    retry_count=retries,
                    last_error_at=datetime.now(timezone.utc),
                )
                session.add(dl)

            await self.bus.publish_dead_letter(
                original_event=event,
                error_message=error_msg,
                stack_trace=stack_trace,
                retry_count=retries,
            )
        except Exception as ex:
            logger.critical(f"Failed to record dead letter event: {ex}")

    async def handle_event(self, event: BaseEvent):
        """Dispatches event to domain handlers based on event_type."""
        logger.info(f"Handling event: {event.event_type} ({event.event_id}) entity={event.entity_id}")

        if event.event_type == "job.discovered.v1":
            await self._handle_job_discovered(event)
        elif event.event_type == "job.matched.v1":
            await self._handle_job_matched(event)
        elif event.event_type == "job.qualified.v1":
            await self._handle_job_qualified(event)
        elif event.event_type == "documents.generated.v1":
            await self._handle_documents_generated(event)
        elif event.event_type == "application.analyzed.v1":
            await self._handle_application_analyzed(event)
        elif event.event_type == "application.submitted.v1":
            await self._handle_application_submitted(event)
        elif event.event_type in ("application.failed.v1", "application.blocked.v1"):
            await self._handle_application_failed_or_blocked(event)
        else:
            logger.debug(f"No specific handler for event type: {event.event_type}")

    async def _handle_job_discovered(self, event: BaseEvent):
        payload = event.payload
        source = payload.get("source", "workable")
        source_job_id = payload.get("source_job_id", "")
        company = payload.get("company", "")
        title = payload.get("title", "")
        application_url = payload.get("application_url") or payload.get("url", "")

        job_fp = compute_job_fingerprint(company, title, application_url)

        async with get_session() as session:
            existing = await find_existing_job(session, source, source_job_id, job_fp)
            if existing is not None:
                logger.info(f"Job duplicate detected for {company} - {title} ({source}:{source_job_id})")
                return

            job_id = UUID(event.entity_id) if event.entity_id else uuid4()
            job = Job(
                id=job_id,
                source=source,
                source_job_id=source_job_id,
                company=company,
                title=title,
                url=payload.get("url", ""),
                application_url=application_url,
                location=payload.get("location"),
                remote_status=payload.get("remote_status"),
                description=payload.get("description"),
                requirements=payload.get("requirements", []),
                publication_metadata=payload.get("publication_metadata", {}),
                job_fingerprint=job_fp,
                status=PipelineStatus.NORMALIZED.value,
                raw_data=payload,
            )
            session.add(job)

        mode = AutomationMode(settings.AUTOMATION_MODE)
        allowed, reason = can_advance_mode(PipelineStatus.MATCHED, mode)
        if allowed:
            logger.info(f"Job {job_id} normalized; ready for matching")
        else:
            logger.info(f"Job {job_id} halted after discovery: {reason}")

    async def _handle_job_matched(self, event: BaseEvent):
        payload = event.payload
        job_id = UUID(event.entity_id)
        score = float(payload.get("overall_score", 0.0))
        qualification = payload.get("qualification", "NOT_QUALIFIED")

        async with get_session() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalars().first()
            if not job:
                logger.warning(f"Job {job_id} not found during job.matched handling")
                return

            # Check threshold
            if score >= settings.MIN_MATCH_SCORE and qualification == "QUALIFIED":
                job.status = PipelineStatus.QUALIFIED.value
                qualified_event = JobQualifiedEvent(
                    correlation_id=event.correlation_id,
                    entity_id=str(job_id),
                    payload={"overall_score": score, "qualification": qualification},
                )
                await self.bus.publish(qualified_event)
                logger.info(f"Job {job_id} qualified with score {score} >= {settings.MIN_MATCH_SCORE}")
            else:
                job.status = PipelineStatus.MATCHED.value
                logger.info(f"Job {job_id} matched but did not meet qualification threshold (score={score})")

    async def _handle_job_qualified(self, event: BaseEvent):
        job_id = event.entity_id
        mode = AutomationMode(settings.AUTOMATION_MODE)
        allowed, reason = can_advance_mode(PipelineStatus.DOCUMENTS_READY, mode)
        if allowed:
            logger.info(f"Job {job_id} qualified; triggering document generation")
        else:
            logger.info(f"Halting at QUALIFIED for job {job_id}: {reason}")

    async def _handle_documents_generated(self, event: BaseEvent):
        job_id = UUID(event.entity_id)
        async with get_session() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalars().first()
            if job:
                job.status = PipelineStatus.DOCUMENTS_READY.value

        mode = AutomationMode(settings.AUTOMATION_MODE)
        allowed, reason = can_advance_mode(PipelineStatus.FORM_ANALYZED, mode)
        if allowed:
            logger.info(f"Documents ready for job {job_id}; triggering application analysis")
        else:
            logger.info(f"Halting at DOCUMENTS_READY for job {job_id}: {reason}")

    async def _handle_application_analyzed(self, event: BaseEvent):
        payload = event.payload
        job_id = UUID(event.entity_id)
        candidate_id = payload.get("candidate_id", "default_candidate")

        async with get_session() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalars().first()
            if not job:
                logger.warning(f"Job {job_id} not found during application analysis")
                return

            app_fp = compute_application_fingerprint(candidate_id, job.job_fingerprint)

            # Check duplicate and submission eligibility
            eligible, reason = await check_submission_eligibility(session, app_fp)
            if not eligible:
                logger.warning(f"Application rejected for job {job_id}: {reason}")
                return

            app_id = uuid4()
            application = Application(
                id=app_id,
                job_id=job_id,
                candidate_id=candidate_id,
                application_fingerprint=app_fp,
                status=PipelineStatus.READY_TO_APPLY.value,
                automation_mode=settings.AUTOMATION_MODE,
            )
            session.add(application)
            job.status = PipelineStatus.READY_TO_APPLY.value
            logger.info(f"Application {app_id} created for job {job_id}, status=READY_TO_APPLY")

    async def _handle_application_submitted(self, event: BaseEvent):
        app_id = UUID(event.entity_id)
        async with get_session() as session:
            stmt = select(Application).where(Application.id == app_id)
            res = await session.execute(stmt)
            app = res.scalars().first()
            if app:
                app.status = PipelineStatus.SUBMITTED.value
                app.last_attempted_at = datetime.now(timezone.utc)
                logger.info(f"Application {app_id} marked as SUBMITTED")

    async def _handle_application_failed_or_blocked(self, event: BaseEvent):
        app_id = UUID(event.entity_id)
        payload = event.payload
        reason = payload.get("reason", "Unknown failure")

        async with get_session() as session:
            stmt = select(Application).where(Application.id == app_id)
            res = await session.execute(stmt)
            app = res.scalars().first()
            if app:
                if event.event_type == "application.blocked.v1":
                    app.status = PipelineStatus.BLOCKED.value
                    app.blocked_reason = reason
                    logger.warning(f"Application {app_id} marked as BLOCKED: {reason}")
                else:
                    app.status = PipelineStatus.FAILED.value
                    app.failure_reason = reason
                    logger.error(f"Application {app_id} marked as FAILED: {reason}")


async def main():
    worker = OrchestratorWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    try:
        await worker.start()
    except (KeyboardInterrupt, SystemExit):
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
