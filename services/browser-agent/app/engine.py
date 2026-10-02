"""BrowserAutomationEngine: page lifecycle, blocker detection, fill, submit.

Submit exists ONLY here (never on adapters) and fires only when the caller
passes submit=True AND confirmed=True AND the automation mode allows it
(FULL_AUTO + AUTO_SUBMIT). In PREPARE_APPLICATION mode nothing is submitted.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from shared.config import settings
from shared.contracts.events import (
    ApplicationBlockedEvent,
    ApplicationFailedEvent,
    ApplicationFilledEvent,
    ApplicationSubmittedEvent,
)
from shared.contracts.models import PipelineStatus
from shared.db.models import (
    Application,
    ApplicationAnswer,
    ApplicationQuestion,
    AutomationRun,
    Job,
)
from shared.db.session import get_session
from shared.profile.loader import CanonicalProfile

from browser.site_adapters.base import FieldPlan, FillResult
from browser.site_adapters.registry import resolve

logger = logging.getLogger(__name__)

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Apply')",
    "button:has-text('Send Application')",
]

# DB question types that map onto plan field kinds.
_KIND_BY_QUESTION_TYPE = {
    "text": "text",
    "email": "text",
    "phone": "text",
    "textarea": "text",
    "select": "select",
    "radio": "select",
    "file": "file",
    "checkbox": "checkbox",
}


class BrowserAutomationEngine:
    def __init__(self, profile: Optional[CanonicalProfile] = None, bus: Any = None):
        self.profile = profile
        self.bus = bus

    # ------------------------------------------------------------------ plan

    def build_plan(
        self,
        questions: List[ApplicationQuestion],
        answers: List[ApplicationAnswer],
    ) -> List[FieldPlan]:
        """Builds a fill plan from verified answers only (never guesses)."""
        verified: Dict[Any, Any] = {}
        for ans in answers:
            if (
                ans.is_verified
                and ans.answer_value
                and isinstance(ans.answer_value, dict)
            ):
                verified[ans.question_id] = ans.answer_value.get("value")

        plan = [
            FieldPlan(
                key=q.question_key,
                label_hint=q.question_text or q.question_key,
                value=verified.get(q.id),
                kind=_KIND_BY_QUESTION_TYPE.get((q.question_type or "text").lower(), "text"),
            )
            for q in questions
        ]

        if self.profile is not None and self.profile.name:
            parts = self.profile.name.split()
            plan.extend(
                [
                    FieldPlan("first_name", "First Name", parts[0], "text"),
                    FieldPlan("last_name", "Last Name", " ".join(parts[1:]), "text"),
                    FieldPlan("email", "Email", self.profile.email, "text"),
                    FieldPlan("phone", "Phone", self.profile.phone, "text"),
                    FieldPlan("firstname", "First Name", parts[0], "text"),
                    FieldPlan("lastname", "Last Name", " ".join(parts[1:]), "text"),
                ]
            )
        return plan

    # ------------------------------------------------------------- page flow

    async def run(
        self,
        url: str,
        plan: List[FieldPlan],
        *,
        submit: bool = False,
        confirmed: bool = False,
        app_id: Optional[UUID] = None,
        on_submitting: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> FillResult:
        """Fills the page via the resolved adapter. Never submits unless the
        caller passes submit=True with confirmed=True in an allowed mode."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Cannot fill forms.")
            return FillResult()

        adapter = resolve(url)
        logger.info(f"Using '{adapter.name}' site adapter for {url}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=settings.BROWSER_HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            try:
                logger.info(f"Navigating to {url}")
                await page.goto(url, wait_until="networkidle", timeout=30000)

                blocked = await adapter.detect_blockers(page)
                if blocked is not None:
                    logger.warning(f"{blocked} detected on {url}; stopping for a human")
                    await browser.close()
                    return FillResult(blocked_reason=blocked)

                result = await adapter.fill(page, plan)
                logger.info(
                    f"Filled {len(result.filled)} fields, "
                    f"skipped {len(result.skipped_unverified)} unverified"
                )

                if app_id is not None:
                    try:
                        await page.screenshot(
                            path=f"/app/browser-traces/app_{app_id}_filled.png",
                            full_page=True,
                        )
                    except Exception as ss_err:
                        logger.debug(f"Screenshot failed (non-fatal): {ss_err}")

                if submit and confirmed and self._submit_allowed():
                    if on_submitting is not None:
                        await on_submitting()
                    result.submitted = await self._click_submit(page)
                    if not result.submitted:
                        logger.warning("No submit button found")
                elif submit:
                    logger.info("Submit requested without confirmation/mode approval; skipped")
                return result
            except Exception as nav_err:
                logger.error(f"Navigation/fill error: {nav_err}")
                raise
            finally:
                await browser.close()

    def _submit_allowed(self) -> bool:
        return settings.AUTOMATION_MODE == "FULL_AUTO" and settings.AUTO_SUBMIT

    async def _click_submit(self, page: Any) -> bool:
        try:
            for selector in SUBMIT_SELECTORS:
                button = await page.query_selector(selector)
                if button and await button.is_visible() and await button.is_enabled():
                    await button.click()
                    await page.wait_for_timeout(3000)
                    logger.info("Submit clicked")
                    return True
        except Exception as exc:
            logger.error(f"Submit failed: {exc}")
        return False

    # -------------------------------------------------------- application flow

    def _unresolved_blocking(self, questions, answers) -> List[ApplicationQuestion]:
        answered = {a.question_id for a in answers if a.is_verified}
        return [
            q
            for q in questions
            if q.classification in ("LEGAL_OR_WORK_AUTHORIZATION",)
            and q.is_required
            and q.id not in answered
        ]

    async def run_application(
        self, app_id: UUID, *, submit: bool = False, confirmed: bool = False
    ) -> str:
        """Full flow for one application. Returns FILLED | SUBMITTED | FAILED | BLOCKED."""
        from sqlalchemy import select

        run_id = uuid4()
        async with get_session() as session:
            app = (
                await session.execute(select(Application).where(Application.id == app_id))
            ).scalars().first()
            if not app:
                logger.warning(f"Application {app_id} not found in database")
                return "FAILED"
            job = (
                await session.execute(select(Job).where(Job.id == app.job_id))
            ).scalars().first()
            if not job:
                logger.warning(f"Job {app.job_id} not found for application {app_id}")
                return "FAILED"
            answers = (
                await session.execute(
                    select(ApplicationAnswer).where(ApplicationAnswer.application_id == app_id)
                )
            ).scalars().all()
            questions = (
                await session.execute(
                    select(ApplicationQuestion).where(ApplicationQuestion.application_id == app_id)
                )
            ).scalars().all()

        application_url = job.application_url or job.url
        logger.info(f"Browser agent starting for application {app_id}, job: {job.company} - {job.title}")
        logger.info(f"Application URL: {application_url}")

        async with get_session() as session:
            session.add(
                AutomationRun(
                    id=run_id,
                    application_id=app_id,
                    job_id=job.id,
                    run_type="BROWSER_FILL",
                    status="STARTED",
                    started_at=datetime.now(timezone.utc),
                )
            )

        try:
            unresolved = self._unresolved_blocking(questions, answers)
            if unresolved:
                reason = (
                    f"Cannot proceed: {len(unresolved)} unresolved blocking questions: "
                    f"{[q.question_key for q in unresolved[:3]]}"
                )
                logger.warning(f"Application {app_id} BLOCKED: {reason}")
                await self._mark(app_id, PipelineStatus.BLOCKED.value, blocked_reason=reason)
                await self._finalize(run_id, "BLOCKED", reason)
                await self._publish(
                    ApplicationBlockedEvent(
                        correlation_id=f"browser-{uuid4().hex[:8]}",
                        entity_id=str(app_id),
                        payload={"reason": reason, "job_id": str(job.id)},
                    )
                )
                return "BLOCKED"

            plan = self.build_plan(questions, answers)

            async def mark_submitting() -> None:
                await self._mark(app_id, PipelineStatus.SUBMITTING.value)

            result = await self.run(
                application_url,
                plan,
                submit=submit,
                confirmed=confirmed,
                app_id=app_id,
                on_submitting=mark_submitting,
            )

            if result.blocked_reason is not None:
                reason = "Browser agent encountered unresolvable challenge (CAPTCHA/MFA/login)"
                await self._mark(app_id, PipelineStatus.BLOCKED.value, blocked_reason=reason)
                await self._finalize(run_id, "BLOCKED", reason)
                await self._publish(
                    ApplicationBlockedEvent(
                        correlation_id=f"browser-{uuid4().hex[:8]}",
                        entity_id=str(app_id),
                        payload={"reason": reason},
                    )
                )
                return "BLOCKED"

            if result.submitted:
                await self._mark(app_id, PipelineStatus.SUBMITTED.value)
                await self._finalize(run_id, "COMPLETED")
                await self._publish(
                    ApplicationSubmittedEvent(
                        correlation_id=f"browser-{uuid4().hex[:8]}",
                        entity_id=str(app_id),
                        payload={"job_id": str(job.id), "company": job.company},
                    )
                )
                logger.info(f"Application {app_id} successfully submitted")
                return "SUBMITTED"

            await self._mark(app_id, PipelineStatus.FILLED.value)
            await self._finalize(run_id, "COMPLETED")
            await self._publish(
                ApplicationFilledEvent(
                    correlation_id=f"browser-{uuid4().hex[:8]}",
                    entity_id=str(app_id),
                    payload={"job_id": str(job.id), "company": job.company, "title": job.title},
                )
            )
            logger.info(f"Application {app_id} successfully filled")
            return "FILLED"

        except Exception as e:
            logger.error(f"Browser agent error for application {app_id}: {e}", exc_info=True)
            reason = str(e)
            await self._mark(app_id, PipelineStatus.FAILED.value, failure_reason=reason)
            await self._finalize(run_id, "FAILED", reason)
            await self._publish(
                ApplicationFailedEvent(
                    correlation_id=f"browser-{uuid4().hex[:8]}",
                    entity_id=str(app_id),
                    payload={"reason": reason},
                )
            )
            return "FAILED"

    async def _publish(self, event: Any) -> None:
        if self.bus is not None:
            await self.bus.publish(event)

    async def _mark(
        self,
        app_id: UUID,
        status: str,
        blocked_reason: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        try:
            from sqlalchemy import select

            async with get_session() as session:
                app = (
                    await session.execute(select(Application).where(Application.id == app_id))
                ).scalars().first()
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

    async def _finalize(
        self, run_id: UUID, status: str, error_message: Optional[str] = None
    ) -> None:
        try:
            from sqlalchemy import select

            now = datetime.now(timezone.utc)
            async with get_session() as session:
                run = (
                    await session.execute(select(AutomationRun).where(AutomationRun.id == run_id))
                ).scalars().first()
                if run:
                    run.status = status
                    run.finished_at = now
                    if run.started_at:
                        run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
                    if error_message:
                        run.error_message = error_message
        except Exception as e:
            logger.error(f"Failed to finalize automation run {run_id}: {e}")
