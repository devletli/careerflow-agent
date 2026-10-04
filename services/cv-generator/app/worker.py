import argparse
import asyncio
import logging
import signal
from uuid import UUID, uuid4
from sqlalchemy import select

from shared.config import settings
from shared.contracts.events import DocumentsGeneratedEvent
from shared.contracts.models import PipelineStatus
from shared.db.models import Application, Job, JobMatch, Document
from shared.db.session import get_session, check_db_health
from shared.infra.redis_bus import RedisEventBus
from shared.infra.heartbeat import beat
from shared.infra.jsonlog import correlation, install_json_logging
from shared.profile.loader import load_canonical_profile
from app.generator import DocumentGenerator

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cv-generator")

CONSUMER_GROUP = "cv-generator-group"
CONSUMER_NAME = f"cv-gen-{uuid4().hex[:6]}"


class CVGeneratorWorker:
    def __init__(self):
        self.bus = RedisEventBus()
        self.profile = load_canonical_profile()
        self.generator = DocumentGenerator()
        self.running = False

    async def generate_for_job(self, job_id: UUID) -> bool:
        """Generates documents for a qualified job and saves to MinIO and DB."""
        async with get_session() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalars().first()
            if not job:
                logger.warning(f"Job {job_id} not found for document generation")
                return False

            stmt_m = select(JobMatch).where(JobMatch.job_id == job_id)
            res_m = await session.execute(stmt_m)
            match_rec = res_m.scalars().first()
            matching_skills = match_rec.matching_skills if match_rec else []

            # Generate documents (grounding gate inside: ungrounded artifacts
            # are never persisted and come back as violations instead).
            generated_docs, violations = self.generator.generate_tailored_documents(
                job_id=job.id,
                company=job.company,
                title=job.title,
                description=job.description or "",
                matching_skills=matching_skills,
                profile=self.profile,
            )

            if violations:
                logger.warning(
                    f"Grounding violations for job {job_id}: "
                    f"{[(v.kind, v.claim) for v in violations]}"
                )
                job.status = PipelineStatus.DOC_REVIEW_REQUIRED.value
                return False

            # Link fresh documents to the latest application of this job, if any.
            stmt_a = (
                select(Application.id)
                .where(Application.job_id == job.id)
                .order_by(Application.created_at.desc())
                .limit(1)
            )
            latest_app_id = (await session.execute(stmt_a)).scalars().first()

            # Persist to database
            for doc_model in generated_docs:
                # Check if document already exists
                stmt_d = select(Document).where(
                    (Document.job_id == job.id)
                    & (Document.type == doc_model.type)
                    & (Document.language == doc_model.language)
                    & (Document.version == doc_model.version)
                )
                res_d = await session.execute(stmt_d)
                existing = res_d.scalars().first()
                if not existing:
                    db_doc = Document(
                        id=uuid4(),
                        job_id=job.id,
                        application_id=latest_app_id,
                        type=doc_model.type,
                        language=doc_model.language,
                        version=doc_model.version,
                        file_path=doc_model.file_path,
                        minio_bucket=doc_model.minio_bucket,
                        minio_key=doc_model.minio_key,
                        mime_type=doc_model.mime_type,
                        content_hash=doc_model.content_hash,
                        metadata_json=doc_model.metadata,
                    )
                    session.add(db_doc)
                else:
                    existing.minio_bucket = doc_model.minio_bucket
                    existing.minio_key = doc_model.minio_key
                    existing.file_path = doc_model.file_path
                    existing.mime_type = doc_model.mime_type
                    existing.content_hash = doc_model.content_hash
                    existing.metadata_json = doc_model.metadata
                    if existing.application_id is None:
                        existing.application_id = latest_app_id

            job.status = PipelineStatus.DOCUMENTS_READY.value

        # Emit documents.generated.v1
        correlation_id = f"gen-{uuid4().hex[:8]}"
        doc_ev = DocumentsGeneratedEvent(
            correlation_id=correlation_id,
            entity_id=str(job_id),
            payload={
                "job_id": str(job_id),
                "documents_count": len(generated_docs),
                "language": generated_docs[0].language if generated_docs else "en",
            },
        )
        await self.bus.publish(doc_ev)
        logger.info(f"Generated {len(generated_docs)} tailored documents for job {job_id}")
        return True

    async def generate_all_pending(self) -> int:
        """Finds all QUALIFIED jobs without documents and generates them."""
        count = 0
        async with get_session() as session:
            stmt = select(Job.id).where(
                Job.status.in_(
                    [
                        PipelineStatus.QUALIFIED.value,
                        PipelineStatus.DOCUMENTS_READY.value,
                        PipelineStatus.READY_TO_APPLY.value,
                        # Re-validate review jobs: fixed templates heal them.
                        PipelineStatus.DOC_REVIEW_REQUIRED.value,
                    ]
                )
            )
            res = await session.execute(stmt)
            job_ids = res.scalars().all()

        for j_id in job_ids:
            ok = await self.generate_for_job(j_id)
            if ok:
                count += 1
        return count

    async def start(self, once: bool = False):
        self.running = True
        if settings.LOG_FORMAT == "json":
            install_json_logging()
        logger.info("CV generator worker starting...")

        for _ in range(15):
            if await check_db_health() and await self.bus.ping():
                break
            await asyncio.sleep(2)

        await self.bus.ensure_consumer_group(settings.STREAM_EVENTS, CONSUMER_GROUP)

        # Initial sweep
        await self.generate_all_pending()
        if once:
            return

        while self.running:
            try:
                # Gorev 7: her turda heartbeat (mesaj olsun olmasin).
                await beat(await self.bus.get_redis(), "cv-generator")
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
                            and event.payload.get("action") == "generate_documents"
                        ):
                            logger.info("Received manual document generation request correlation_id=%s", event.correlation_id)
                            await self.generate_all_pending()
                        elif event.event_type == "job.qualified.v1":
                            try:
                                job_id = UUID(event.entity_id)
                                await self.generate_for_job(job_id)
                            except Exception as e:
                                logger.error(f"Error generating documents for {event.entity_id}: {e}", exc_info=True)
                        await self.bus.ack(settings.STREAM_EVENTS, CONSUMER_GROUP, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in CV generator loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def stop(self):
        self.running = False
        await self.bus.close()


async def main():
    parser = argparse.ArgumentParser(description="CV Generator Worker")
    parser.add_argument("--once", action="store_true", help="Generate documents for all pending qualified jobs and exit")
    args = parser.parse_args()

    worker = CVGeneratorWorker()

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
