"""Operational endpoints. Written for the 3 a.m. debugging session."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, get_now, require_admin
from app.container import Container

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/diagnostics", summary="Everything you need in one call")
async def diagnostics(
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> dict:
    crossings = container.crossings.list_active(session)
    return {
        "now": now.isoformat(),
        "environment": container.settings.environment,
        "started_at": container.started_at.isoformat(),
        "last_ingest_tick": (
            container.ingest.last_tick_at.isoformat()
            if container.ingest.last_tick_at else None
        ),
        "budget": container.budget.snapshot(),
        "providers": container.chain.snapshot(),
        "provider_health": [asdict(h) for h in await container.chain.health()],
        "crossings": [
            {
                "slug": c.slug,
                "name": c.name,
                "segment": f"{c.prev_station_code} → {c.next_station_code}",
                "calibration": [
                    {"train_class": k, "samples": v.sample_count,
                     "pass_offset_seconds": round(v.pass_offset_seconds, 1)}
                    for k, v in container.learning.load_calibration(
                        session, c.id
                    ).by_class.items()
                ],
            }
            for c in crossings
        ],
    }


@router.post("/ingest", summary="Force an ingest tick now")
async def force_ingest(
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
) -> dict:
    results = await container.ingest.run_all(session)
    return {"ticks": [asdict(r) for r in results]}


@router.post("/grade", summary="Force prediction grading now")
def force_grade(
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> dict:
    graded = {
        c.slug: container.learning.grade_pending(session, c.id, now)
        for c in container.crossings.list_active(session)
    }
    return {"graded": graded}


@router.post("/geometry/review", summary="Run the geometry calibrator now")
def review_geometry(
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> dict:
    reviews = [
        asdict(container.geometry.review(session, crossing, now))
        for crossing in container.crossings.list_active(session)
    ]
    return {"reviews": reviews}


@router.get("/geometry/history", summary="Audit trail of automatic corrections")
def geometry_history(
    container: Container = Depends(get_container),
    session: Session = Depends(get_db),
) -> dict:
    out = {}
    for crossing in container.crossings.list_active(session):
        out[crossing.slug] = [
            {
                "applied_at": adj.applied_at.isoformat(),
                "delta_km": adj.delta_km,
                "old_distance_from_prev_km": adj.old_distance_from_prev_km,
                "new_distance_from_prev_km": adj.new_distance_from_prev_km,
                "evidence": adj.evidence,
                "note": adj.note,
            }
            for adj in container.geometry.history(session, crossing.id)
        ]
    return out


@router.post("/cache/clear", summary="Flush the response cache")
async def clear_cache(container: Container = Depends(get_container)) -> dict:
    await container.cache.clear()
    return {"cleared": True}
