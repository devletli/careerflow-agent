FROM python:3.12-slim
WORKDIR /app

COPY services/orchestrator/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
RUN pip install --no-cache-dir -e ./shared

# Copy Alembic config and migrations for init-db
COPY db/alembic.ini ./alembic.ini
COPY db/migrations ./migrations

COPY scripts/healthcheck_worker.py ./scripts/healthcheck_worker.py
COPY scripts/backfill_document_application_link.py ./scripts/backfill_document_application_link.py
COPY scripts/export_for_labeling.py ./scripts/export_for_labeling.py
COPY services/orchestrator/app ./app
ENV PYTHONPATH=/app

CMD ["python", "-m", "app.worker"]
