import argparse
import asyncio
import logging
import signal
from uuid import UUID, uuid4

from sqlalchemy import select

from shared.config import settings
from shared.contracts.models import PipelineStatus
from shared.db.models import Application
from shared.db.session import check_db_health, get_session
from shared.infra.redis_bus import RedisEventBus
from shared.profile.loader import load_canonical_profile

from app.engine import BrowserAutomationEngine

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("browser-agent")

CONSUMER_GROUP = "browser-agent-group"
CONSUMER_NAME = f"browser-{uuid4().hex[:6]}"


class BrowserAgentWorker:
    """Redis consumer: delegates application processing to the engine."""

    def __init__(self):
        self.bus = RedisEventBus()
        self.profile = load_canonical_profile()
        self.engine = BrowserAutomationEngine(self.profile, self.bus)
        self.running = False

    async def process_ready_applications(self) -> int:
        """Finds all READY_TO_APPLY applications and processes them."""
        count = 0
        async with get_session() as session:
            res = await session.execute(
                select(Application.id).where(
                    Application.status == PipelineStatus.READY_TO_APPLY.value
                )
            )
            app_ids = res.scalars().all()

        for app_id in app_ids:
            try:
                result = await self.engine.run_application(app_id)
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
                # T5: crashed-worker pending messages first (replay is idempotent).
                reclaimed = await self.bus.reclaim_events(settings.STREAM_EVENTS, CONSUMER_GROUP, CONSUMER_NAME)
                events = reclaimed + await self.bus.read_events(
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
                            await self.engine.run_application(
                                UUID(application_id), submit=True, confirmed=True
                            )
                        except (TypeError, ValueError):
                            logger.error(
                                "Rejected submit request with invalid application_id=%r",
                                application_id,
                            )
                    elif event.event_type == "application.ready.v1":
                        try:
                            app_id = UUID(event.entity_id)
                            await self.engine.run_application(app_id)
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
