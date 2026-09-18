FROM python:3.12-slim
WORKDIR /app

COPY services/application-analyzer/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
RUN pip install --no-cache-dir -e ./shared

COPY services/application-analyzer/app ./app
COPY profile ./profile

ENV PYTHONPATH=/app

CMD ["python", "-m", "app.worker"]
