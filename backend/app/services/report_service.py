"""Crowd gate reports.

A tap from someone standing at the gate is the only signal that sees freight,
which no public data source publishes. It is also an unauthenticated write on a
public endpoint, so it has to be designed on the assumption that some of it is
wrong, duplicated, or deliberately false.

The defence is layered, cheapest first:

1. **Cooldown** — one report per client, per crossing, per
   ``report_cooldown_seconds``. Stops the honest double-tap, which is by far
   the most common duplicate.
2. **IP ceiling** — a per-hour cap keyed on a salted hash of the client IP,
   for when someone clears storage to mint a fresh identity.
3. **Corroboration** — a lone report is a hint; independent reports of the
   same state inside the corroboration window are evidence. The count is
   recorded on the observation and consumers weigh it.
4. **Bounded blast radius** — and this is the one that actually matters.

On (4): crowd reports are deliberately *not* allowed to move timing offsets.
The calibration loop is driven only by provider ``actualArrival`` times, which
we cannot forge. A report can do exactly two things — corroborate a closure we
already predicted, or flag one we did not (the freight signal, surfaced as a
risk band). So the worst a successful abuse campaign achieves is an inflated
"freight risk" percentage. It cannot shift a single countdown. Rate limiting
buys time; limiting what the data is *permitted to influence* is what makes
abuse uninteresting.

Identity note: we hash a client-generated random id and never store the id
itself. It identifies a browser, not a person, and there is no account, cookie
or tracking behind it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import ClosureWindow, Crossing, GateReport, Observation, ObservationSource

logger = get_logger(__name__)


class ReportOutcome(str, Enum):
    RECORDED = "recorded"
    CORROBORATED = "corroborated"
    UNEXPLAINED = "unexplained"
    DUPLICATE = "duplicate"
    RATE_LIMITED = "rate_limited"


_MESSAGES: dict[ReportOutcome, str] = {
    ReportOutcome.RECORDED: "Thanks — recorded.",
    ReportOutcome.CORROBORATED: "Thanks — that matches what we predicted.",
    ReportOutcome.UNEXPLAINED: (
        "Thanks — we didn't predict this one. Unexplained closures are usually "
        "freight, and they feed the risk estimate."
    ),
    ReportOutcome.DUPLICATE: "Already recorded your report for this closure.",
    ReportOutcome.RATE_LIMITED: "That's a lot of reports — try again a bit later.",
}


@dataclass(frozen=True, slots=True)
class ReportResult:
    outcome: ReportOutcome
    message: str
    accepted: bool
    next_report_at: datetime | None
    corroborations: int = 0
    report_id: int | None = None


def _hash(value: str, salt: str = "phaatak") -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


class ReportService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def submit(
        self,
        session: Session,
        crossing: Crossing,
        state: str,
        now: datetime,
        *,
        client_id: str | None = None,
        client_ip: str | None = None,
        note: str | None = None,
    ) -> ReportResult:
        cooldown = timedelta(seconds=self._settings.report_cooldown_seconds)
        client_hash = _hash(client_id) if client_id else None
        ip_hash = _hash(client_ip, salt="phaatak-ip") if client_ip else None

        recent = self._recent_from_client(session, crossing.id, client_hash, now, cooldown)
        if recent is not None:
            return ReportResult(
                outcome=ReportOutcome.DUPLICATE,
                message=_MESSAGES[ReportOutcome.DUPLICATE],
                accepted=False,
                next_report_at=recent.reported_at + cooldown,
            )

        if self._ip_over_limit(session, ip_hash, now):
            return ReportResult(
                outcome=ReportOutcome.RATE_LIMITED,
                message=_MESSAGES[ReportOutcome.RATE_LIMITED],
                accepted=False,
                next_report_at=now + timedelta(hours=1),
            )

        report = GateReport(
            crossing_id=crossing.id,
            state=state,
            reported_at=now,
            client_hash=client_hash,
            ip_hash=ip_hash,
            note=note,
        )
        session.add(report)
        session.flush()

        outcome, corroborations = self._interpret(session, crossing, state, now, report)
        return ReportResult(
            outcome=outcome,
            message=_MESSAGES[outcome],
            accepted=True,
            next_report_at=now + cooldown,
            corroborations=corroborations,
            report_id=report.id,
        )

    # ------------------------------------------------------------- guards

    def _recent_from_client(
        self,
        session: Session,
        crossing_id: int,
        client_hash: str | None,
        now: datetime,
        cooldown: timedelta,
    ) -> GateReport | None:
        if client_hash is None:
            # An anonymous client cannot be deduplicated; the IP ceiling is the
            # only guard left, so we do not silently accept unlimited reports.
            return None
        return session.scalars(
            select(GateReport)
            .where(
                GateReport.crossing_id == crossing_id,
                GateReport.client_hash == client_hash,
                GateReport.reported_at > now - cooldown,
            )
            .order_by(GateReport.reported_at.desc())
            .limit(1)
        ).first()

    def _ip_over_limit(self, session: Session, ip_hash: str | None, now: datetime) -> bool:
        if ip_hash is None:
            return False
        count = session.scalar(
            select(func.count(GateReport.id)).where(
                GateReport.ip_hash == ip_hash,
                GateReport.reported_at > now - timedelta(hours=1),
            )
        )
        return bool(count and count >= self._settings.report_ip_hourly_limit)

    # ------------------------------------------------------- interpretation

    def _interpret(
        self,
        session: Session,
        crossing: Crossing,
        state: str,
        now: datetime,
        report: GateReport,
    ) -> tuple[ReportOutcome, int]:
        """Turn a report into an observation, and decide what it means.

        Only "closed" reports carry information we can act on: either the
        closure was predicted (the model was right) or it was not (something
        invisible closed the gate — almost always freight).
        """
        window = timedelta(seconds=self._settings.report_corroboration_window_seconds)
        corroborations = self._count_corroborations(session, crossing.id, state, now, window)

        if state != "closed":
            session.add(
                Observation(
                    crossing_id=crossing.id,
                    source=ObservationSource.USER_REPORT.value,
                    observed_open_at=now,
                    is_unexplained=False,
                    detail={"report_id": report.id, "corroborations": corroborations},
                )
            )
            return ReportOutcome.RECORDED, corroborations

        predicted = self._closure_covering(session, crossing.id, now)
        unexplained = predicted is None
        session.add(
            Observation(
                crossing_id=crossing.id,
                source=ObservationSource.USER_REPORT.value,
                observed_close_at=now,
                # The freight signal. Deliberately the only thing crowd data is
                # allowed to move — see this module's docstring.
                is_unexplained=unexplained,
                detail={
                    "report_id": report.id,
                    "corroborations": corroborations,
                    "matched_window_id": None if predicted is None else predicted.id,
                },
            )
        )
        if unexplained:
            logger.info(
                "unexplained closure reported at %s (crossing %s) — freight signal",
                now.isoformat(), crossing.slug,
            )
            return ReportOutcome.UNEXPLAINED, corroborations
        return ReportOutcome.CORROBORATED, corroborations

    def _closure_covering(
        self, session: Session, crossing_id: int, moment: datetime
    ) -> ClosureWindow | None:
        """A predicted closure that contains this instant, with a small grace
        period — a gate reported shut 60 s before our predicted close is the
        same event, not a different one."""
        grace = timedelta(minutes=2)
        return session.scalars(
            select(ClosureWindow)
            .where(
                ClosureWindow.crossing_id == crossing_id,
                ClosureWindow.is_superseded.is_(False),
                ClosureWindow.close_at <= moment + grace,
                ClosureWindow.open_at >= moment - grace,
            )
            .limit(1)
        ).first()

    def _count_corroborations(
        self,
        session: Session,
        crossing_id: int,
        state: str,
        now: datetime,
        window: timedelta,
    ) -> int:
        """Distinct clients reporting the same state in the window, including
        this one. Distinct — ten taps from one browser is still one witness."""
        count = session.scalar(
            select(func.count(func.distinct(GateReport.client_hash))).where(
                GateReport.crossing_id == crossing_id,
                GateReport.state == state,
                GateReport.reported_at > now - window,
                GateReport.client_hash.is_not(None),
            )
        )
        return int(count or 1)
