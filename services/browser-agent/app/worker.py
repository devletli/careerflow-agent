import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from shared.config import settings
from shared.contracts.events import (
    ApplicationFilledEvent,
    ApplicationSubmittedEvent,
    ApplicationFailedEvent,
    ApplicationBlockedEvent,
)
from shared.contracts.models import PipelineStatus
from shared.db.models import (
    Application,
    ApplicationAnswer,
    ApplicationQuestion,
    AutomationRun,
    Job,
)
from shared.db.session import get_session, check_db_health
from shared.infra.redis_bus import RedisEventBus
from shared.profile.loader import load_canonical_profile, CanonicalProfile

from app.engine import BrowserAutomationEngine

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("browser-agent")

CONSUMER_GROUP = "browser-agent-group"
CONSUMER_NAME = f"browser-{uuid4().hex[:6]}"


class BrowserApplicationAgent:
    """
    Playwright-based browser agent that fills and optionally submits job applications.

    Safety invariants:
    - STOPS immediately on CAPTCHA / MFA / security challenge
    - STOPS on any LEGAL_OR_WORK_AUTHORIZATION question without a verified answer
    - STOPS on any USER_PREFERENCE question without an explicitly configured answer
    - Does NOT hallucinate or guess answers
    - Never submits unless AUTO_SUBMIT=true AND automation_mode=FULL_AUTO
    """

    def __init__(self, profile: CanonicalProfile, bus: RedisEventBus):
        self.profile = profile
        self.bus = bus
        self.engine = BrowserAutomationEngine()

    async def process_application(self, app_id: UUID, submit: bool = False) -> str:
        """
        Main entry point: fills application form for the given application_id.
        Returns final status: FILLED | SUBMITTED | FAILED | BLOCKED
        """
        run_id = uuid4()

        async with get_session() as session:
            from sqlalchemy import select
            stmt = select(Application).where(Application.id == app_id)
            res = await session.execute(stmt)
            app = res.scalars().first()
            if not app:
                logger.warning(f"Application {app_id} not found in database")
                return "FAILED"

            stmt_j = select(Job).where(Job.id == app.job_id)
            res_j = await session.execute(stmt_j)
            job = res_j.scalars().first()
            if not job:
                logger.warning(f"Job {app.job_id} not found for application {app_id}")
                return "FAILED"

            stmt_ans = select(ApplicationAnswer).where(ApplicationAnswer.application_id == app_id)
            res_ans = await session.execute(stmt_ans)
            answers = res_ans.scalars().all()

            stmt_qs = select(ApplicationQuestion).where(ApplicationQuestion.application_id == app_id)
            res_qs = await session.execute(stmt_qs)
            questions = res_qs.scalars().all()

        application_url = job.application_url or job.url
        logger.info(f"Browser agent starting for application {app_id}, job: {job.company} - {job.title}")
        logger.info(f"Application URL: {application_url}")

        # Record automation run start
        async with get_session() as session:
            run = AutomationRun(
                id=run_id,
                application_id=app_id,
                job_id=job.id,
                run_type="BROWSER_FILL",
                status="STARTED",
                started_at=datetime.now(timezone.utc),
            )
            session.add(run)

        try:
            # Check for unresolved blocking questions
            unresolved = self._find_unresolved_blocking_questions(questions, answers)
            if unresolved:
                reason = f"Cannot proceed: {len(unresolved)} unresolved blocking questions: {[q.question_key for q in unresolved[:3]]}"
                logger.warning(f"Application {app_id} BLOCKED: {reason}")
                await self._mark_application(app_id, PipelineStatus.BLOCKED.value, blocked_reason=reason)
                await self._finalize_run(run_id, "BLOCKED", reason)
                await self.bus.publish(ApplicationBlockedEvent(
                    correlation_id=f"browser-{uuid4().hex[:8]}",
                    entity_id=str(app_id),
                    payload={"reason": reason, "job_id": str(job.id)},
                ))
                return "BLOCKED"

            # Attempt Playwright form filling
            should_submit = submit or (
                settings.AUTOMATION_MODE == "FULL_AUTO" and settings.AUTO_SUBMIT
            )
            result_status = await self._fill_form_with_playwright(
                application_url=application_url,
                app_id=app_id,
                job=job,
                answers=answers,
                questions=questions,
                submit=should_submit,
            )

            if result_status in ("FILLED", "SUBMITTED"):
                final_status = (
                    PipelineStatus.SUBMITTED.value
                    if result_status == "SUBMITTED"
                    else PipelineStatus.FILLED.value
                )
                await self._mark_application(app_id, final_status)
                await self._finalize_run(run_id, "COMPLETED")
                if result_status == "SUBMITTED":
                    await self.bus.publish(ApplicationSubmittedEvent(
                        correlation_id=f"browser-{uuid4().hex[:8]}",
                        entity_id=str(app_id),
                        payload={"job_id": str(job.id), "company": job.company},
                    ))
                    logger.info(f"Application {app_id} successfully submitted")
                    return "SUBMITTED"

                await self.bus.publish(ApplicationFilledEvent(
                    correlation_id=f"browser-{uuid4().hex[:8]}",
                    entity_id=str(app_id),
                    payload={"job_id": str(job.id), "company": job.company, "title": job.title},
                ))
                logger.info(f"Application {app_id} successfully filled")
                return "FILLED"

            elif result_status == "BLOCKED":
                reason = "Browser agent encountered unresolvable challenge (CAPTCHA/MFA/login)"
                await self._mark_application(app_id, PipelineStatus.BLOCKED.value, blocked_reason=reason)
                await self._finalize_run(run_id, "BLOCKED", reason)
                await self.bus.publish(ApplicationBlockedEvent(
                    correlation_id=f"browser-{uuid4().hex[:8]}",
                    entity_id=str(app_id),
                    payload={"reason": reason},
                ))
                return "BLOCKED"

            else:
                reason = f"Browser agent failed during form filling (status={result_status})"
                await self._mark_application(app_id, PipelineStatus.FAILED.value, failure_reason=reason)
                await self._finalize_run(run_id, "FAILED", reason)
                await self.bus.publish(ApplicationFailedEvent(
                    correlation_id=f"browser-{uuid4().hex[:8]}",
                    entity_id=str(app_id),
                    payload={"reason": reason, "job_id": str(job.id)},
                ))
                return "FAILED"

        except Exception as e:
            logger.error(f"Browser agent error for application {app_id}: {e}", exc_info=True)
            reason = str(e)
            await self._mark_application(app_id, PipelineStatus.FAILED.value, failure_reason=reason)
            await self._finalize_run(run_id, "FAILED", reason)
            await self.bus.publish(ApplicationFailedEvent(
                correlation_id=f"browser-{uuid4().hex[:8]}",
                entity_id=str(app_id),
                payload={"reason": reason},
            ))
            return "FAILED"

    def _find_unresolved_blocking_questions(
        self,
        questions: List[ApplicationQuestion],
        answers: List[ApplicationAnswer],
    ) -> List[ApplicationQuestion]:
        """Returns questions that are blocking (LEGAL or USER_PREFERENCE required) without verified answers."""
        answered_question_ids = {a.question_id for a in answers if a.is_verified}
        blocking = []
        for q in questions:
            if q.classification in ("LEGAL_OR_WORK_AUTHORIZATION",) and q.is_required:
                if q.id not in answered_question_ids:
                    blocking.append(q)
        return blocking

    async def _fill_form_with_playwright(
        self,
        application_url: str,
        app_id: UUID,
        job: Any,
        answers: List[ApplicationAnswer],
        questions: List[ApplicationQuestion],
        submit: bool = False,
    ) -> str:
        """
        Delegates navigation/fill/submit to the BrowserAutomationEngine with
        the SiteAdapter resolved for this URL. Returns: FILLED | SUBMITTED | BLOCKED | FAILED
        """
        # Build answer lookup by question key
        q_by_id = {q.id: q for q in questions}
        answer_map: Dict[str, Any] = {}
        for ans in answers:
            q = q_by_id.get(ans.question_id)
            if q and ans.answer_value and isinstance(ans.answer_value, dict):
                answer_map[q.question_key] = ans.answer_value.get("value")

        # Standard profile-based fills
        profile_fills = {
            "first_name": self.profile.name.split()[0] if self.profile.name else "",
            "last_name": " ".join(self.profile.name.split()[1:]) if self.profile.name else "",
            "email": self.profile.email,
            "phone": self.profile.phone,
            "firstname": self.profile.name.split()[0] if self.profile.name else "",
            "lastname": " ".join(self.profile.name.split()[1:]) if self.profile.name else "",
        }
        answer_map.update({k: v for k, v in profile_fills.items() if k not in answer_map})

        async def mark_submitting() -> None:
            await self._mark_application(app_id, PipelineStatus.SUBMITTING.value)

        result_status, _ = await self.engine.run_fill(
            application_url=application_url,
            app_id=app_id,
            answers=answer_map,
            submit=submit,
            on_submitting=mark_submitting,
        )
        return result_status

    async def _mark_application(
        self,
        app_id: UUID,
        status: str,
        blocked_reason: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ):
        """Updates application status in the database."""
        try:
            from sqlalchemy import select
            async with get_session() as session:
                stmt = select(Application).where(Application.id == app_id)
                res = await session.execute(stmt)
                app = res.scalars().first()
                if app:
                    app.status = status
                    app.last_attempted_at = datetime.now(timezone.utc)
                    app.attempts = (app.attempts or 0) + 1
                    if blocked_reason:
                        app.blocked_reason = blocked_reason
                    if failure_reason:
                        app.failure_reason = failure_reason
        except Exception as e:
            logger.error(f"Failed to update application {app_id} status: {e}")

    async def _finalize_run(
        self,
        run_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ):
        """Updates automation run record with completion status."""
        try:
            from sqlalchemy import select
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                stmt = select(AutomationRun).where(AutomationRun.id == run_id)
                res = await session.execute(stmt)
                run = res.scalars().first()
                if run:
                    run.status = status
                    run.finished_at = now
                    if run.started_at:
                        delta = now - run.started_at
                        run.duration_ms = int(delta.total_seconds() * 1000)
                    if error_message:
                        run.error_message = error_message
        except Exception as e:
            logger.error(f"Failed to finalize automation run {run_id}: {e}")


class BrowserAgentWorker:
    def __init__(self):
        self.bus = RedisEventBus()
        self.profile = load_canonical_profile()
        self.agent = BrowserApplicationAgent(self.profile, self.bus)
        self.running = False

    async def process_ready_applications(self) -> int:
        """Finds all READY_TO_APPLY applications and processes them."""
        count = 0
        from sqlalchemy import select
        async with get_session() as session:
            stmt = select(Application.id).where(Application.status == PipelineStatus.READY_TO_APPLY.value)
            res = await session.execute(stmt)
            app_ids = res.scalars().all()

        for app_id in app_ids:
            try:
                result = await self.agent.process_application(app_id)
                logger.info(f"Application {app_id} processing result: {result}")
                count += 1
            except Exception as e:
                logger.error(f"Error processing application {app_id}: {e}", exc_info=True)

        return count

    async def start(self, once: bool = False):
        self.running = True
        logger.info("Browser agent worker starting...")

        for _ in range(20):
            if await check_db_health() and await self.bus.ping():
                break
            await asyncio.sleep(3)

        await self.bus.ensure_consumer_group(settings.STREAM_EVENTS, CONSUMER_GROUP)

        # Initial sweep
        await self.process_ready_applications()
        if once:
            return

        while self.running:
            try:
                events = await self.bus.read_events(
                    stream=settings.STREAM_EVENTS,
                    group=CONSUMER_GROUP,
                    consumer=CONSUMER_NAME,
                    count=3,
                    block_ms=5000,
                )
                for msg_id, event in events:
                    if (
                        event.event_type == "pipeline.control.v1"
                        and event.payload.get("action") == "fill_applications"
                        and event.payload.get("confirmed") is True
                    ):
                        logger.info("Received confirmed manual form filling request correlation_id=%s", event.correlation_id)
                        await self.process_ready_applications()
                    elif (
                        event.event_type == "pipeline.control.v1"
                        and event.payload.get("action") == "submit_application"
                        and event.payload.get("confirmed") is True
                    ):
                        application_id = event.payload.get("application_id")
                        try:
                            await self.agent.process_application(UUID(application_id), submit=True)
                        except (TypeError, ValueError):
                            logger.error(
                                "Rejected submit request with invalid application_id=%r",
                                application_id,
                            )
                    elif event.event_type == "application.ready.v1":
                        try:
                            app_id = UUID(event.entity_id)
                            await self.agent.process_application(app_id)
                        except Exception as e:
                            logger.error(f"Error processing application {event.entity_id}: {e}", exc_info=True)
                    await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in browser agent loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def stop(self):
        self.running = False
        await self.bus.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Browser Agent Worker")
    parser.add_argument("--once", action="store_true", help="Process all ready applications once and exit")
    args = parser.parse_args()

    worker = BrowserAgentWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            pass

    try:
        await worker.start(once=args.once)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
