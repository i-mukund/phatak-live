"""Read path.

Projects materialised closure windows onto "now" and shapes the single payload
the app renders. Deliberately performs **no network I/O**: a user request must
never be able to hang on an upstream API (failure modes F1–F3).

If the scheduler has not produced fresh windows — cold start, crashed worker,
total provider outage — we synthesise windows on the spot from the offline
timetable, which is a local database read. The response is then flagged
``stale``/``degraded`` and its confidence drops, but it is never empty.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import to_ist
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import ClosureWindow as ClosureWindowRow
from app.db.models import Crossing
from app.domain import CrossingRef, Direction, TrainClass
from app.providers.base import FetchContext
from app.providers.timetable import TimetableProvider
from app.schemas.status import (
    ApproachingTrainOut,
    ClosureWindowOut,
    ConfidenceOut,
    CrossingStatusOut,
    DataQualityOut,
    LeaveAdviceOut,
    TodaySummaryOut,
    TrainCauseOut,
)
from app.services.crossing_service import to_ref, to_summary
from app.services.learning.engine import LearningEngine
from app.services.prediction.engine import PredictionEngine, merge_windows
from app.services.prediction.model import (
    ClosureWindow,
    Estimator,
    GateState,
    TrainCause,
)

logger = get_logger(__name__)


def confidence_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "moderate"
    if score >= 0.4:
        return "low"
    return "very low"


class StatusService:
    def __init__(
        self,
        *,
        engine: PredictionEngine,
        learning: LearningEngine,
        settings: Settings,
        fallback_provider: TimetableProvider,
    ) -> None:
        self._engine = engine
        self._learning = learning
        self._settings = settings
        self._fallback = fallback_provider

    async def get_status(
        self,
        session: Session,
        crossing: Crossing,
        now: datetime,
        *,
        travel_seconds: int | None = None,
    ) -> CrossingStatusOut:
        ref = to_ref(crossing)
        windows, last_updated, stale = self._load_windows(session, crossing.id, now)

        degraded = stale
        providers_used: list[str] = []
        notes: list[str] = []

        if not windows:
            # Freshly computed from the local timetable: degraded (no live
            # data) but *not* stale — the numbers were produced just now.
            windows, notes = await self._fallback_windows(session, ref, now)
            degraded, stale = True, False
            providers_used = [self._fallback.name]
            last_updated = now

        state = self._state(windows, now)
        current = next((w for w in windows if w.contains(now)), None)
        upcoming = [w for w in windows if w.close_at > now]
        next_window = upcoming[0] if upcoming else None

        relevant = current or next_window
        score = relevant.confidence if relevant else (0.55 if degraded else 0.7)
        if stale:
            score *= 0.7
            notes.append("Live data is stale; showing the last known prediction.")

        return CrossingStatusOut(
            crossing=to_summary(crossing),
            generated_at=last_updated or now,
            server_time=now,
            state=state.value,
            seconds_until_close=(
                (next_window.close_at - now).total_seconds() if next_window else None
            ),
            seconds_until_open=((current.open_at - now).total_seconds() if current else None),
            current_closure=_window_out(current) if current else None,
            next_closure=_window_out(next_window) if next_window else None,
            upcoming=[_window_out(w) for w in upcoming[:6]],
            approaching_train=_approaching(next_window or current),
            confidence=ConfidenceOut(
                score=round(min(max(score, 0.05), 0.97), 3),
                label=confidence_label(score),
                factors={},
                notes=notes
                or (["Freight movements are not visible to any public data source."]
                    if not windows else []),
            ),
            today=self._today(session, ref, now),
            data=DataQualityOut(
                providers_used=providers_used or _providers_in(windows),
                degraded=degraded,
                stale=stale,
                freight_risk=self._learning.freight_risk(session, crossing.id, now),
                last_updated_at=last_updated,
                notes=notes,
            ),
            advice=self._advice(windows, now, travel_seconds),
        )

    # ------------------------------------------------------------- loading

    def _load_windows(
        self, session: Session, crossing_id: int, now: datetime
    ) -> tuple[list[ClosureWindow], datetime | None, bool]:
        rows = list(
            session.scalars(
                select(ClosureWindowRow)
                .where(
                    ClosureWindowRow.crossing_id == crossing_id,
                    ClosureWindowRow.is_superseded.is_(False),
                    ClosureWindowRow.open_at >= now - timedelta(minutes=30),
                    ClosureWindowRow.close_at
                    <= now + timedelta(minutes=self._settings.prediction_horizon_minutes),
                )
                .order_by(ClosureWindowRow.close_at)
            )
        )
        if not rows:
            return [], None, True
        last_updated = max(row.updated_at for row in rows)
        stale = (
            now - last_updated
        ).total_seconds() > self._settings.max_sighting_age_seconds
        return [_row_to_window(r) for r in rows], last_updated, stale

    async def _fallback_windows(
        self, session: Session, ref: CrossingRef, now: datetime
    ) -> tuple[list[ClosureWindow], list[str]]:
        ctx = FetchContext(
            crossing=ref,
            now=now,
            horizon_minutes=self._settings.prediction_horizon_minutes,
            live_call_allowance=0,
        )
        try:
            sightings = await self._fallback.fetch_sightings(ctx)
        except Exception:
            logger.exception("timetable fallback failed for %s", ref.slug)
            return [], ["No prediction data is currently available."]

        prediction = self._engine.predict(
            crossing=ref,
            sightings=sightings,
            now=now,
            calibration=self._learning.load_calibration(session, ref.id),
            degraded=True,
            providers_used=(self._fallback.name,),
        )
        note = (
            "Showing scheduled timings — no live train data is available right now."
            if sightings
            else "No trains are scheduled at this crossing in the next two hours."
        )
        return list(prediction.windows), [note]

    # ------------------------------------------------------------ shaping

    def _state(self, windows: list[ClosureWindow], now: datetime) -> GateState:
        if any(w.contains(now) for w in windows):
            return GateState.CLOSED
        nxt = next((w for w in windows if w.close_at > now), None)
        if nxt and (nxt.close_at - now).total_seconds() <= self._engine.closing_soon_seconds:
            return GateState.CLOSING_SOON
        return GateState.OPEN

    def _today(self, session: Session, ref: CrossingRef, now: datetime) -> TodaySummaryOut:
        local = to_ist(now)
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start_local.astimezone(now.tzinfo)
        end = (start_local + timedelta(days=1)).astimezone(now.tzinfo)

        rows = list(
            session.scalars(
                select(ClosureWindowRow)
                .where(
                    ClosureWindowRow.crossing_id == ref.id,
                    ClosureWindowRow.is_superseded.is_(False),
                    ClosureWindowRow.close_at >= start,
                    ClosureWindowRow.close_at < end,
                    ClosureWindowRow.close_at <= now,
                )
                .order_by(ClosureWindowRow.close_at.desc())
            )
        )
        windows = merge_windows(
            [_row_to_window(r) for r in rows], ref.min_gate_cycle_seconds
        )
        durations = [w.duration_seconds for w in windows]
        return TodaySummaryOut(
            date=start_local.date().isoformat(),
            closure_count=len(windows),
            total_closed_seconds=round(sum(durations), 1),
            longest_closure_seconds=round(max(durations), 1) if durations else 0.0,
            closures=[_window_out(w) for w in sorted(windows, key=lambda w: w.close_at,
                                                     reverse=True)[:12]],
        )

    def _advice(
        self, windows: list[ClosureWindow], now: datetime, travel_seconds: int | None
    ) -> LeaveAdviceOut | None:
        if travel_seconds is None:
            return None
        arrival = now + timedelta(seconds=travel_seconds)
        blocking = next((w for w in windows if w.contains(arrival)), None)
        if blocking is None:
            nxt = next((w for w in windows if w.close_at > arrival), None)
            margin = (nxt.close_at - arrival).total_seconds() if nxt else None
            if margin is not None and margin < 120:
                margin_text = (
                    f"{round(margin)} s" if margin < 60
                    else f"{int(margin // 60)} min {int(margin % 60)} s"
                )
                return LeaveAdviceOut(
                    travel_seconds=travel_seconds,
                    arrival_at=arrival,
                    can_cross=True,
                    verdict="tight",
                    reason=(
                        "You should just make it — the gate is expected to close "
                        f"about {margin_text} after you arrive."
                    ),
                )
            return LeaveAdviceOut(
                travel_seconds=travel_seconds,
                arrival_at=arrival,
                can_cross=True,
                verdict="go",
                reason="The gate is expected to be open when you arrive.",
            )
        wait = (blocking.open_at - arrival).total_seconds()
        leave_in = (blocking.open_at - now).total_seconds()
        # "about 0 min of waiting" is what integer division produces for a
        # sub-minute wait, and it reads like a bug to the person holding keys.
        wait_text = "under a minute" if wait < 60 else f"about {round(wait / 60)} min"
        leave_text = (
            "in about a minute" if leave_in < 90 else f"in {round(leave_in / 60)} min"
        )
        return LeaveAdviceOut(
            travel_seconds=travel_seconds,
            arrival_at=arrival,
            can_cross=False,
            verdict="wait",
            reason=(
                f"The gate is expected to be shut when you arrive — {wait_text} "
                f"of waiting. Leaving {leave_text} avoids it."
            ),
        )


# ---------------------------------------------------------------- helpers


def _row_to_window(row: ClosureWindowRow) -> ClosureWindow:
    causes = []
    for raw in row.causes or []:
        try:
            causes.append(
                TrainCause(
                    train_number=raw["train_number"],
                    train_name=raw.get("train_name", raw["train_number"]),
                    train_class=TrainClass(raw.get("train_class", "unknown")),
                    direction=Direction(raw.get("direction", "unknown")),
                    pass_at=datetime.fromisoformat(raw["pass_at"]),
                    speed_kmph=float(raw.get("speed_kmph", 0.0)),
                    delay_minutes=int(raw.get("delay_minutes", 0)),
                    provider=raw.get("provider", "unknown"),
                    estimator=Estimator(raw.get("estimator", "schedule")),
                )
            )
        except (KeyError, ValueError):
            # A single malformed cause must not take down the status endpoint.
            logger.warning("skipping malformed cause on window %s", row.id)
    return ClosureWindow(
        close_at=row.close_at,
        open_at=row.open_at,
        confidence=row.confidence,
        causes=tuple(causes),
    )


def _window_out(window: ClosureWindow) -> ClosureWindowOut:
    return ClosureWindowOut(
        close_at=window.close_at,
        open_at=window.open_at,
        duration_seconds=round(window.duration_seconds, 1),
        confidence=round(window.confidence, 3),
        causes=[
            TrainCauseOut(
                train_number=c.train_number,
                train_name=c.train_name,
                train_class=c.train_class.value,
                direction=c.direction.value,
                pass_at=c.pass_at,
                speed_kmph=c.speed_kmph,
                delay_minutes=c.delay_minutes,
                provider=c.provider,
                estimator=c.estimator.value,
            )
            for c in window.causes
        ],
    )


def _approaching(window: ClosureWindow | None) -> ApproachingTrainOut | None:
    if window is None or not window.causes:
        return None
    cause = min(window.causes, key=lambda c: c.pass_at)
    return ApproachingTrainOut(
        train_number=cause.train_number,
        train_name=cause.train_name,
        train_class=cause.train_class.value,
        direction=cause.direction.value,
        pass_at=cause.pass_at,
        speed_kmph=cause.speed_kmph,
        delay_minutes=cause.delay_minutes,
    )


def _providers_in(windows: list[ClosureWindow]) -> list[str]:
    seen: list[str] = []
    for window in windows:
        for cause in window.causes:
            if cause.provider not in seen:
                seen.append(cause.provider)
    return seen


__all__ = ["StatusService", "confidence_label"]
