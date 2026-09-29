FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "sqlalchemy[asyncio]>=2.0.36" asyncpg pydantic opentelemetry-sdk opentelemetry-exporter-otlp opentelemetry-instrumentation-fastapi
WORKDIR /app
COPY sandbox/pesa ./pesa
RUN useradd -m app && chown -R app /app
USER app
CMD ["uvicorn", "pesa.main:app", "--host", "0.0.0.0", "--port", "8001"]
