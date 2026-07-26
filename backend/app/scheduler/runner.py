"""APScheduler wiring.

In-process on purpose: three cron jobs do not justify a broker (ARCHITECTURE
§6). ``max_instances=1`` and ``coalesce=True`` mean a slow tick is skipped
rather than queued, which is the correct behaviour for polling — a backlog of
stale ingests helps nobody (failure mode F9).

When we outgrow one box, this file is the only thing that changes: the jobs
themselves are plain functions over the container.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.container import Container
from app.core.logging import get_logger
from app.scheduler.jobs import calibration_job, ingest_job, observation_job, retention_job

logger = get_logger(__name__)


def build_scheduler(container: Container) -> AsyncIOScheduler:
    settings = container.settings
    scheduler = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_job(
        ingest_job, "interval", seconds=settings.ingest_interval_seconds,
        args=[container], id="ingest", next_run_time=None,
    )
    scheduler.add_job(
        observation_job, "interval", seconds=settings.observation_interval_seconds,
        args=[container], id="observe",
    )
    scheduler.add_job(
        calibration_job, "interval", seconds=settings.calibration_interval_seconds,
        args=[container], id="calibrate",
    )
    scheduler.add_job(
        retention_job, "interval", seconds=settings.retention_interval_seconds,
        args=[container], id="retention",
    )
    logger.info(
        "scheduler configured (ingest every %ss)", settings.ingest_interval_seconds
    )
    return scheduler
