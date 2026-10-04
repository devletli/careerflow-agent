import argparse
import asyncio
import logging
import signal
from typing import Optional
from uuid import UUID, uuid4
import httpx
from sqlalchemy import select

from shared.config import settings
from shared.contracts.events import (
    ApplicationAnalyzedEvent,
    ApplicationReadyEvent,
)
from shared.contracts.fingerprint import compute_application_fingerprint
from shared.contracts.models import PipelineStatus
from shared.db.models import (
    Job,
    Application,
    ApplicationQuestion,
    ApplicationAnswer,
)
from shared.db.session import get_session, check_db_health
from shared.infra.redis_bus import RedisEventBus
from shared.infra.jsonlog import correlation
from shared.profile.loader import load_canonical_profile
from app.analyzer import FormAnalyzer

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("application-analyzer")

CONSUMER_GROUP = "analyzer-group"
CONSUMER_NAME = f"analyzer-{uuid4().hex[:6]}"


class ApplicationAnalyzerWorker:
    def __init__(self):
        self.bus = RedisEventBus()
        self.profile = load_canonical_profile()
        self.analyzer = FormAnalyzer()
        self.running = False

    async def analyze_job_application(self, job_id: UUID) -> Optional[Application]:
        """Inspects application form, classifies questions, and stores answers."""
        async with get_session() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalars().first()
            if not job:
                logger.warning(f"Job {job_id} not found for application analysis")
                return None

            app_url = job.application_url or job.url
            html_content = ""
            try:
                from shared.infra.urls import assert_public_http_url

                assert_public_http_url(app_url)
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
                    resp = await client.get(app_url)
                    if resp.status_code == 200:
                        html_content = resp.text
            except Exception as e:
                logger.debug(f"Could not fetch live form HTML from {app_url} ({e}); using baseline analysis")

            fields, questions = self.analyzer.analyze_form(app_url, html_content)
            candidate_id = self.profile.facts.get("candidate_id", "default-candidate")
            app_fp = compute_application_fingerprint(candidate_id, job.job_fingerprint)

            # Find or create application
            stmt_a = select(Application).where(Application.application_fingerprint == app_fp)
            res_a = await session.execute(stmt_a)
            app = res_a.scalars().first()

            if not app:
                app = Application(
                    id=uuid4(),
                    job_id=job.id,
                    candidate_id=candidate_id,
                    application_fingerprint=app_fp,
                    status=PipelineStatus.READY_TO_APPLY.value,
                    automation_mode=settings.AUTOMATION_MODE,
                )
                session.add(app)
            else:
                app.status = PipelineStatus.READY_TO_APPLY.value

            # Save questions & answers
            for q in questions:
                stmt_q = select(ApplicationQuestion).where(
                    (ApplicationQuestion.application_id == app.id)
                    & (ApplicationQuestion.question_key == q.key)
                )
                res_q = await session.execute(stmt_q)
                db_q = res_q.scalars().first()

                if not db_q:
                    db_q = ApplicationQuestion(
                        id=uuid4(),
                        application_id=app.id,
                        question_key=q.key,
                        question_text=q.text,
                        question_type=q.type,
                        is_required=q.is_required,
                        raw_options=q.options,
                        classification=q.classification.value,
                        confidence=q.confidence,
                    )
                    session.add(db_q)

                ans_val, ans_src, is_ver = self.analyzer.resolve_answer(q, self.profile)
                if ans_val is not None:
                    # Idempotent: skip if this question was already answered
                    # (re-analysis after event redelivery must not violate
                    # uq_application_answers_app_question).
                    stmt_a = select(ApplicationAnswer).where(
                        (ApplicationAnswer.application_id == app.id)
                        & (ApplicationAnswer.question_id == db_q.id)
                    )
                    res_a = await session.execute(stmt_a)
                    if res_a.scalars().first() is not None:
                        continue
                    db_ans = ApplicationAnswer(
                        id=uuid4(),
                        application_id=app.id,
                        question_id=db_q.id,
                        answer_value={"value": ans_val},
                        answer_source=ans_src,
                        is_verified=is_ver,
                    )
                    session.add(db_ans)

            job.status = PipelineStatus.READY_TO_APPLY.value

        # Emit events
        correlation_id = f"analyzed-{uuid4().hex[:8]}"
        analyzed_ev = ApplicationAnalyzedEvent(
            correlation_id=correlation_id,
            entity_id=str(app.id),
            payload={
                "job_id": str(job_id),
                "fields_count": len(fields),
                "questions_count": len(questions),
                "ats": self.analyzer.detect_ats(app_url, html_content),
            },
        )
        ready_ev = ApplicationReadyEvent(
            correlation_id=correlation_id,
            entity_id=str(app.id),
            payload={
                "job_id": str(job_id),
                "application_fingerprint": app_fp,
            },
        )
        await self.bus.publish(analyzed_ev)
        await self.bus.publish(ready_ev)
        logger.info(f"Analyzed application for job {job_id}; status=READY_TO_APPLY ({len(fields)} fields)")
        return app

    async def analyze_all_pending(self) -> int:
        """Finds all DOCUMENTS_READY jobs and analyzes application pages."""
        count = 0
        async with get_session() as session:
            stmt = select(Job.id).where(Job.status == PipelineStatus.DOCUMENTS_READY.value)
            res = await session.execute(stmt)
            job_ids = res.scalars().all()

        for j_id in job_ids:
            try:
                res_app = await self.analyze_job_application(j_id)
                if res_app:
                    count += 1
            except Exception as e:
                logger.error(f"Error analyzing pending job {j_id}: {e}", exc_info=True)
        return count

    async def start(self, once: bool = False):
        self.running = True
        logger.info("Application analyzer worker starting...")

        for _ in range(15):
            if await check_db_health() and await self.bus.ping():
                break
            await asyncio.sleep(2)

        await self.bus.ensure_consumer_group(settings.STREAM_EVENTS, CONSUMER_GROUP)

        # Initial sweep
        await self.analyze_all_pending()
        if once:
            return

        while self.running:
            try:
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
                            and event.payload.get("action") == "analyze_applications"
                        ):
                            logger.info("Received manual application analysis request correlation_id=%s", event.correlation_id)
                            await self.analyze_all_pending()
                        elif event.event_type == "documents.generated.v1":
                            try:
                                job_id = UUID(event.entity_id)
                                await self.analyze_job_application(job_id)
                            except Exception as e:
                                logger.error(f"Error analyzing application for {event.entity_id}: {e}", exc_info=True)
                        await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in analyzer loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def stop(self):
        self.running = False
        await self.bus.close()


async def main():
    parser = argparse.ArgumentParser(description="Application Analyzer Worker")
    parser.add_argument("--once", action="store_true", help="Analyze all pending jobs once and exit")
    args = parser.parse_args()

    worker = ApplicationAnalyzerWorker()

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
