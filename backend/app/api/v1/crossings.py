"""Crossing discovery and the status endpoint the app polls."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, get_now, require_admin
from app.container import Container
from app.schemas.crossing import CrossingCreate, CrossingDetail, CrossingSummary
from app.schemas.status import (
    AccuracyOut,
    CrossingStatusOut,
    GateReportIn,
    GateReportOut,
)
from app.services.crossing_service import to_detail, to_summary

router = APIRouter(prefix="/crossings", tags=["crossings"])


@router.get("", response_model=list[CrossingSummary], summary="List crossings")
def list_crossings(
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
) -> list[CrossingSummary]:
    return [to_summary(c) for c in container.crossings.list_active(session)]


@router.get("/{slug}", response_model=CrossingDetail, summary="Crossing detail")
def get_crossing(
    slug: str,
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
) -> CrossingDetail:
    return to_detail(container.crossings.get_by_slug(session, slug))


@router.get(
    "/{slug}/status",
    response_model=CrossingStatusOut,
    summary="Current and predicted gate status",
    description=(
        "The single endpoint the app polls. Countdowns are **not** returned as "
        "durations — every instant is an absolute ISO-8601 timestamp so the "
        "response stays correct while cached. Pass `travel_seconds` to get a "
        "direct 'should I leave now?' verdict."
    ),
)
async def get_status(
    slug: str,
    response: Response,
    travel_seconds: int | None = Query(
        default=None, ge=0, le=7200,
        description="How long it takes you to reach the crossing, in seconds.",
    ),
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> CrossingStatusOut:
    crossing = container.crossings.get_by_slug(session, slug)
    cache_key = f"status:{slug}:{travel_seconds or 0}"
    cached = await container.cache.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "hit"
        # Absolute instants stay valid while cached; the derived countdowns do
        # not, so they are recomputed against the current instant.
        return _refresh_countdowns(CrossingStatusOut.model_validate(cached), now)

    payload = await container.status.get_status(
        session, crossing, now, travel_seconds=travel_seconds
    )
    await container.cache.set(
        cache_key, payload.model_dump(mode="json"),
        container.settings.cache_status_ttl_seconds,
    )
    response.headers["X-Cache"] = "miss"
    response.headers["Cache-Control"] = "public, max-age=10, stale-while-revalidate=30"
    return payload


def _refresh_countdowns(payload: CrossingStatusOut, now: datetime) -> CrossingStatusOut:
    payload.server_time = now
    payload.seconds_until_close = (
        (payload.next_closure.close_at - now).total_seconds()
        if payload.next_closure else None
    )
    payload.seconds_until_open = (
        (payload.current_closure.open_at - now).total_seconds()
        if payload.current_closure else None
    )
    return payload


@router.post(
    "/{slug}/reports",
    response_model=GateReportOut,
    status_code=201,
    summary="Report what the gate is actually doing",
    description=(
        "A person standing at the gate is the highest-quality sensor we have — "
        "especially for freight, which no public data source exposes."
    ),
)
def report_gate(
    slug: str,
    payload: GateReportIn,
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> GateReportOut:
    crossing = container.crossings.get_by_slug(session, slug)
    report = container.learning.record_user_report(
        session, crossing.id, payload.state, now, note=payload.note
    )
    return GateReportOut(id=report.id, state=report.state, reported_at=report.reported_at)


@router.get(
    "/{slug}/accuracy",
    response_model=AccuracyOut,
    summary="How well have we been predicting?",
)
def accuracy(
    slug: str,
    days: int = Query(default=14, ge=1, le=90),
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> AccuracyOut:
    crossing = container.crossings.get_by_slug(session, slug)
    calibration = container.learning.load_calibration(session, crossing.id)
    return AccuracyOut(
        crossing_slug=slug,
        summary=container.learning.accuracy_summary(session, crossing.id, now, days=days),
        calibration=[
            {
                "train_class": key,
                "pass_offset_seconds": round(value.pass_offset_seconds, 1),
                "close_offset_seconds": round(value.close_offset_seconds, 1),
                "open_offset_seconds": round(value.open_offset_seconds, 1),
                "pass_mae_seconds": round(value.pass_mae_seconds, 1),
                "sample_count": value.sample_count,
            }
            for key, value in sorted(calibration.by_class.items())
        ],
    )


@router.post(
    "",
    response_model=CrossingDetail,
    status_code=201,
    dependencies=[Depends(require_admin)],
    summary="Add a crossing (admin)",
)
def create_crossing(
    payload: CrossingCreate,
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
) -> CrossingDetail:
    return to_detail(container.crossings.create(session, payload))
