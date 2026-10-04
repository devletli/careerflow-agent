FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app

COPY services/browser-agent/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
RUN pip install --no-cache-dir -e ./shared

COPY browser ./browser
COPY scripts/healthcheck_worker.py ./scripts/healthcheck_worker.py
COPY services/browser-agent/app ./app
COPY profile ./profile

ENV PYTHONPATH=/app

CMD ["python", "-m", "app.worker"]
