# syntax=docker/dockerfile:1
# Multi-stage: wheels are built once, the runtime image carries no toolchain.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

COPY pyproject.toml ./
RUN pip install --upgrade pip build && \
    pip wheel --wheel-dir /wheels \
        "fastapi>=0.115.0" "uvicorn[standard]>=0.30.0" "pydantic>=2.8.0" \
        "pydantic-settings>=2.4.0" "sqlalchemy>=2.0.30" "alembic>=1.13.0" \
        "httpx>=0.27.0" "apscheduler>=3.10.4" "cachetools>=5.4.0" \
        "python-json-logger>=2.0.7" "prometheus-client>=0.20.0" "psycopg[binary]>=3.2.0"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATABASE_URL=sqlite+pysqlite:////data/phatak.db

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 phatak && \
    mkdir -p /data && chown phatak:phatak /data

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels

COPY --chown=phatak:phatak . .

USER phatak
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT}/health/live" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
