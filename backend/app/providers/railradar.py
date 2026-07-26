"""RailRadar provider — the primary live source.

Ingestion strategy (ADR 0003)
-----------------------------
The crossing sits *inside* one inter-station segment, so two station-live-board
calls enumerate every train that can possibly cross, regardless of how many
trains are running::

    GET /v1/stations/{prev}/live?includeIntermediate=true
    GET /v1/stations/{next}/live?includeIntermediate=true

A train appearing on both boards gives us, for free: direction (from the
reported chainages), a pass time (interpolated between the two expected times)
and an implied segment speed. That is 2 calls per tick, forever.

We then spend a *small, budgeted* number of ``/trains/{n}/live`` calls on the
one or two trains nearest the gate, where ``segmentProgress``, ``speedKmh`` and
``isActualPosition`` genuinely change the answer the user reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.budget import ApiBudget
from app.core.cache import Cache
from app.core.clock import to_ist
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.domain import (
    Direction,
    LivePosition,
    ProviderHealth,
    RouteStop,
    RunStatus,
    TrainSighting,
    classify_train,
)
from app.providers.base import BaseProvider, FetchContext
from app.providers.http import RestClient
from app.providers.parsing import (
    as_bool,
    as_float,
    as_int,
    as_str,
    dig,
    parse_clock_time,
    parse_datetime,
)

logger = get_logger(__name__)

_STATUS_MAP = {
    "running": RunStatus.RUNNING,
    "not-started": RunStatus.NOT_STARTED,
    "completed": RunStatus.COMPLETED,
    "cancelled": RunStatus.CANCELLED,
}


class RailRadarProvider(BaseProvider):
    name = "railradar"
    trust = 0.92

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.railradar.in/v1",
        timeout: float = 8.0,
        cache: Cache | None = None,
        cache_ttl: int = 60,
        client: Any | None = None,
    ) -> None:
        self._client = RestClient(
            provider=self.name,
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout,
            cache=cache,
            cache_ttl=cache_ttl,
            client=client,
        )

    # ------------------------------------------------------------------ API

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        crossing = ctx.crossing
        budget = ctx.budget

        boards = {}
        for code in (crossing.prev_station_code, crossing.next_station_code):
            _spend(budget, essential=True)
            boards[code] = await self._station_board(code, ctx.horizon_minutes)

        sightings = self._sightings_from_boards(
            boards.get(crossing.prev_station_code, {}),
            boards.get(crossing.next_station_code, {}),
            ctx,
        )
        return await self._enrich_nearest(sightings, ctx)

    async def health(self) -> ProviderHealth:
        # Deliberately does not hit the network: health checks must not burn quota.
        return ProviderHealth(name=self.name, healthy=True, detail="configured")

    async def close(self) -> None:
        await self._client.close()

    # -------------------------------------------------------------- boards

    async def _station_board(self, code: str, horizon_minutes: int) -> dict[str, dict[str, Any]]:
        """Return ``{train_number: entry}`` for one station's live board."""
        hours = min((h for h in (2, 4, 6, 8) if h * 60 >= horizon_minutes), default=8)
        payload = await self._client.get_json(
            f"/stations/{code}/live",
            {"hours": hours, "includeIntermediate": "true"},
        )
        if not payload.get("success", True):
            raise ProviderError(self.name, f"envelope error: {dig(payload, 'error', 'message')}")
        entries = dig(payload, "data", "trains", default=[]) or []
        if not isinstance(entries, list):
            raise ProviderError(self.name, "station board 'trains' was not a list",
                                retryable=False)
        board: dict[str, dict[str, Any]] = {}
        for entry in entries:
            number = as_str(dig(entry, "train", "number"))
            if number:
                board[number] = entry
        return board

    def _sightings_from_boards(
        self,
        prev_board: dict[str, dict[str, Any]],
        next_board: dict[str, dict[str, Any]],
        ctx: FetchContext,
    ) -> list[TrainSighting]:
        crossing = ctx.crossing
        out: list[TrainSighting] = []
        for number in set(prev_board) | set(next_board):
            prev_entry, next_entry = prev_board.get(number), next_board.get(number)
            if prev_entry is None or next_entry is None:
                # Seen at only one end. We cannot infer direction or a segment
                # speed from a single board, so we skip rather than guess —
                # a wrong direction is worse than a missing train.
                continue
            sighting = self._build_segment_sighting(number, prev_entry, next_entry, ctx)
            if sighting is not None and sighting.is_actionable:
                out.append(sighting)

        horizon_end = ctx.now + timedelta(minutes=ctx.horizon_minutes)
        return [
            s for s in out
            if _within(_route_pass_hint(s, crossing.distance_from_prev_km), ctx.now, horizon_end)
        ]

    def _build_segment_sighting(
        self,
        number: str,
        prev_entry: dict[str, Any],
        next_entry: dict[str, Any],
        ctx: FetchContext,
    ) -> TrainSighting | None:
        crossing = ctx.crossing
        day = to_ist(ctx.now).date()
        t_prev = self._expected_time(prev_entry, day)
        t_next = self._expected_time(next_entry, day)
        if t_prev is None or t_next is None or t_prev == t_next:
            return None

        d_prev = as_float(dig(prev_entry, "stop", "distance"), 0.0) or 0.0
        d_next = as_float(dig(next_entry, "stop", "distance"), 0.0) or 0.0

        # Chainage grows along the train's own route, so the smaller chainage is
        # the station it reaches first. Timings break ties when chainage is absent.
        forward = d_prev < d_next if d_prev != d_next else t_prev < t_next
        direction = Direction.UP if forward else Direction.DOWN

        first_stop = prev_entry if forward else next_entry
        t_first, t_second = (t_prev, t_next) if forward else (t_next, t_prev)
        if t_second <= t_first:
            return None

        span_km = abs(d_next - d_prev) or ctx.crossing.segment_length_km
        train = first_stop.get("train") or {}
        train_type = as_str(train.get("type"))
        name = as_str(train.get("name"), number) or number
        delay = as_int(dig(first_stop, "live", "delayMinutes"), 0)

        # Synthetic two-stop route expressed in *direction of travel*, using the
        # crossing's own station codes, so the shared geometry resolver treats
        # board-derived and full-route sightings identically.
        first_code = crossing.prev_station_code if forward else crossing.next_station_code
        second_code = crossing.next_station_code if forward else crossing.prev_station_code
        route = (
            RouteStop(
                sequence=1,
                station_code=first_code,
                distance_km=0.0,
                scheduled_departure=t_first,
                status="upcoming" if t_first > ctx.now else "departed",
                actual_departure=t_first if t_first <= ctx.now else None,
                speed_to_next_kmph=_speed_kmph(span_km, t_second - t_first),
            ),
            RouteStop(
                sequence=2,
                station_code=second_code,
                distance_km=span_km,
                scheduled_arrival=t_second,
                status="upcoming",
            ),
        )
        # The synthetic 2-stop route is expressed in *direction of travel*, so
        # the shared geometry resolver treats board data and full route data
        # identically. Chainage of the crossing within it:
        offset_km = (
            crossing.distance_from_prev_km if forward else crossing.distance_from_next_km
        )
        scale = span_km / crossing.segment_length_km if crossing.segment_length_km else 1.0

        return TrainSighting(
            train_number=number,
            train_name=name,
            provider=self.name,
            provider_trust=self.trust,
            observed_at=ctx.now,
            train_class=classify_train(train_type, name),
            train_type=train_type,
            status=RunStatus.RUNNING,
            delay_minutes=delay,
            route=route,
            position=None,
            direct_pass_estimate=_interpolate(
                t_first, t_second, (offset_km * scale) / span_km if span_km else 0.5
            ),
            direct_speed_kmph=_speed_kmph(span_km, t_second - t_first),
            direct_direction=direction,
            raw={"source": "station_board", "prev": prev_entry, "next": next_entry},
        )

    def _expected_time(self, entry: dict[str, Any], day: Any) -> datetime | None:
        live = entry.get("live") or {}
        for key in ("expectedDepartureTime", "expectedArrivalTime", "actualDepartureTime"):
            parsed = parse_datetime(live.get(key))
            if parsed:
                return parsed
        stop = entry.get("stop") or {}
        delay = timedelta(minutes=as_int(live.get("delayMinutes"), 0))
        for key in ("departure", "arrival"):
            parsed = parse_clock_time(stop.get(key), day)
            if parsed:
                return parsed + delay
        return None

    # ------------------------------------------------------------ enrichment

    async def _enrich_nearest(
        self, sightings: list[TrainSighting], ctx: FetchContext
    ) -> list[TrainSighting]:
        """Upgrade the trains closest to the gate with full live detail."""
        allowance = max(0, ctx.live_call_allowance)
        if not allowance or not sightings:
            return sightings

        upcoming = sorted(
            (s for s in sightings if s.direct_pass_estimate and s.direct_pass_estimate >= ctx.now),
            key=lambda s: s.direct_pass_estimate,  # type: ignore[arg-type,return-value]
        )
        enriched: dict[str, TrainSighting] = {}
        for sighting in upcoming[:allowance]:
            if ctx.budget is not None and not ctx.budget.can_spend(essential=False):
                logger.info("budget reserve reached; skipping live enrichment")
                break
            try:
                _spend(ctx.budget, essential=False)
                detailed = await self._live_train(sighting.train_number, ctx)
            except ProviderError as exc:
                # Enrichment is best-effort by design: the board sighting is
                # already good enough to answer the user's question.
                logger.warning("enrichment failed for %s: %s", sighting.train_number, exc)
                continue
            if detailed is not None:
                enriched[detailed.train_number] = detailed
        return [enriched.get(s.train_number, s) for s in sightings]

    async def _live_train(self, number: str, ctx: FetchContext) -> TrainSighting | None:
        payload = await self._client.get_json(
            f"/trains/{number}/live", {"includeCoordinates": "true"}
        )
        if not payload.get("success", True):
            raise ProviderError(self.name, f"envelope error: {dig(payload, 'error', 'message')}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError(self.name, "live status 'data' missing", retryable=False)
        return self.parse_live_train(data, ctx.now)

    def parse_live_train(self, data: dict[str, Any], now: datetime) -> TrainSighting | None:
        """Public for contract tests over recorded fixtures."""
        number = as_str(data.get("trainNumber"))
        if not number:
            return None
        raw_route = data.get("route")
        route: list[RouteStop] = []
        if isinstance(raw_route, list):
            for stop in raw_route:
                code = as_str(stop.get("stationCode"))
                if not code:
                    continue
                route.append(
                    RouteStop(
                        sequence=as_int(stop.get("sequence"), len(route) + 1),
                        station_code=code,
                        station_name=as_str(stop.get("stationName")),
                        distance_km=as_float(stop.get("distance"), 0.0) or 0.0,
                        is_halt=as_bool(stop.get("isHalt"), True),
                        scheduled_arrival=parse_datetime(stop.get("scheduledArrival")),
                        scheduled_departure=parse_datetime(stop.get("scheduledDeparture")),
                        actual_arrival=parse_datetime(stop.get("actualArrival")),
                        actual_departure=parse_datetime(stop.get("actualDeparture")),
                        status=as_str(stop.get("status"), "upcoming") or "upcoming",
                        speed_to_next_kmph=as_float(stop.get("speedToNextStationKmph")),
                        latitude=as_float(stop.get("lat")),
                        longitude=as_float(stop.get("lng")),
                    )
                )
        route.sort(key=lambda s: s.sequence)

        position = None
        loc = data.get("currentLocation")
        if isinstance(loc, dict) and as_str(loc.get("stationCode")):
            position = LivePosition(
                station_code=as_str(loc.get("stationCode")) or "",
                sequence=as_int(loc.get("sequence"), 0),
                segment_progress=as_float(loc.get("segmentProgress"), 0.0) or 0.0,
                speed_kmph=as_float(loc.get("speedKmh")),
                is_actual=as_bool(loc.get("isActualPosition"), False),
            )

        train = data.get("train") or {}
        train_type = as_str(train.get("type")) or as_str(train.get("category"))
        name = as_str(data.get("trainName"), number) or number
        return TrainSighting(
            train_number=number,
            train_name=name,
            provider=self.name,
            provider_trust=self.trust,
            observed_at=parse_datetime(data.get("lastUpdatedAt")) or now,
            train_class=classify_train(train_type, name),
            train_type=train_type,
            status=_STATUS_MAP.get(as_str(data.get("status"), "") or "", RunStatus.RUNNING),
            delay_minutes=as_int(data.get("delayMinutes"), 0),
            route=tuple(route),
            position=position,
            average_speed_kmph=as_float(train.get("avgSpeed")),
            raw={"source": "live_train"},
        )


# ---------------------------------------------------------------- helpers


def _spend(budget: ApiBudget | None, *, essential: bool) -> None:
    if budget is None:
        return
    if not budget.can_spend(essential=essential):
        raise ProviderError("railradar", "daily API budget exhausted", retryable=False)
    budget.spend()


def _speed_kmph(distance_km: float, delta: timedelta) -> float | None:
    seconds = delta.total_seconds()
    if seconds <= 0 or distance_km <= 0:
        return None
    return distance_km / (seconds / 3600.0)


def _interpolate(start: datetime, end: datetime, fraction: float) -> datetime:
    fraction = max(0.0, min(1.0, fraction))
    return start + (end - start) * fraction


def _within(moment: datetime | None, start: datetime, end: datetime) -> bool:
    #: Keep trains that have just passed too — they may still hold the gate shut.
    return moment is not None and start - timedelta(minutes=10) <= moment <= end


def _route_pass_hint(sighting: TrainSighting, _offset_km: float) -> datetime | None:
    return sighting.direct_pass_estimate
