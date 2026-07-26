"""Background jobs.

Each job opens its own transaction and swallows its own exceptions: a failing
job must never kill the scheduler thread or leak a half-open transaction.
"""

from __future__ import annotations

from app.container import Container
from app.core.logging import get_logger
from app.db.session import session_scope

logger = get_logger(__name__)


async def ingest_job(container: Container) -> None:
    try:
        with session_scope() as session:
            await container.ingest.run_all(session)
    except Exception:
        logger.exception("ingest job failed")


def observation_job(container: Container) -> None:
    """Grade elapsed predictions against whatever ground truth has arrived."""
    try:
        now = container.clock.now()
        with session_scope() as session:
            for crossing in container.crossings.list_active(session):
                container.learning.grade_pending(session, crossing.id, now)
    except Exception:
        logger.exception("observation job failed")


def calibration_job(container: Container) -> None:
    """Periodic accuracy logging plus autonomous geometry review.

    EWMA offset calibration happens continuously during grading. This job adds
    the slower loop: if the graded residuals show the directional signature of
    a wrong chainage, the crossing's surveyed distances are corrected in place
    (bounded, rate-limited, audited — see ``learning/geometry.py``).
    """
    try:
        now = container.clock.now()
        with session_scope() as session:
            for crossing in container.crossings.list_active(session):
                summary = container.learning.accuracy_summary(session, crossing.id, now)
                if summary.get("samples"):
                    logger.info("accuracy[%s]: %s", crossing.slug, summary)
                review = container.geometry.review(session, crossing, now)
                if review.adjusted:
                    logger.info("geometry[%s]: adjusted %+.3f km", crossing.slug,
                                review.delta_km)
    except Exception:
        logger.exception("calibration job failed")


def retention_job(container: Container) -> None:
    try:
        now = container.clock.now()
        with session_scope() as session:
            deleted = container.ingest.purge_old(
                session, now, container.settings.retention_days
            )
        if deleted:
            logger.info("retention: purged %d row(s)", deleted)
    except Exception:
        logger.exception("retention job failed")
