"""Liveness, readiness and metrics.

``/live`` and ``/ready`` are separate on purpose: a provider outage must not
cause the orchestrator to restart a perfectly healthy process.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, get_now
from app.container import Container
from app.core.metrics import REGISTRY
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])

VERSION = "1.0.0"


@router.get("/health/live", response_model=HealthResponse, summary="Liveness probe")
def live(
    container: Container = Depends(get_container),
    now: datetime = Depends(get_now),
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=VERSION,
        environment=container.settings.environment,
        time=now,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def ready(
    response: Response,
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
) -> ReadinessResponse:
    try:
        session.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    provider_health = [asdict(h) for h in await container.chain.health()]
    any_provider = any(h["healthy"] for h in provider_health)
    ready_now = database_ok and any_provider
    if not ready_now:
        response.status_code = 503

    return ReadinessResponse(
        status="ready" if ready_now else "not_ready",
        database=database_ok,
        providers=provider_health,
        scheduler_last_tick=container.ingest.last_tick_at,
        degraded=not any_provider,
    )


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
