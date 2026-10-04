FROM python:3.12-slim
WORKDIR /app

COPY services/job-discovery/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
RUN pip install --no-cache-dir -e ./shared

COPY browser ./browser
COPY scripts/healthcheck_worker.py ./scripts/healthcheck_worker.py
COPY services/job-discovery/app ./app
COPY profile ./profile

ENV PYTHONPATH=/app

CMD ["python", "-m", "app.worker"]
