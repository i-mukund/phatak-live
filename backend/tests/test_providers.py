"""Provider contract and parsing tests.

These run against recorded fixtures shaped like the real vendor responses. They
are the early-warning system for an upstream schema change (risk table, §7).
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx

from app.core.budget import ApiBudget
from app.core.clock import FrozenClock
from app.core.errors import ProviderError, ProviderRateLimited, ProviderUnavailable
from app.domain import Direction, TrainClass, classify_train
from app.providers.base import FetchContext
from app.providers.generic_rest import GenericRestProvider
from app.providers.mock import MockProvider
from app.providers.railradar import RailRadarProvider
from app.providers.timetable import TimetableProvider

BASE = "https://api.railradar.test/v1"


def _board_entry(number, name, ttype, distance, iso_time, delay=0):
    return {
        "train": {"number": number, "name": name, "type": ttype,
                  "source": "NDLS", "destination": "UMB"},
        "stop": {"sequence": 4, "arrival": "08:05", "departure": "08:07",
                 "day": 1, "distance": distance},
        "live": {"type": "upcoming", "expectedDepartureTime": iso_time,
                 "platform": "1", "delayMinutes": delay},
    }


def _envelope(trains):
    return {
        "success": True,
        "data": {"station": {"code": "BHD", "name": "Badli"},
                 "window": {"from": "07:00", "to": "11:00"},
                 "count": len(trains), "trains": trains},
        "meta": {"traceId": "t", "timestamp": "2026-07-21T08:00:00+05:30",
                 "executionTime": 12, "source": "database"},
    }


@pytest.fixture
def ctx(ref, now):
    return FetchContext(crossing=ref, now=now, horizon_minutes=120, live_call_allowance=0)


class TestTrainClassification:
    @pytest.mark.parametrize(
        "type_, name, expected",
        [
            ("Superfast Express", "Swaraj Express", TrainClass.SUPERFAST),
            ("Shatabdi Express", "Kalka Shatabdi", TrainClass.SHATABDI),
            (None, "Vande Bharat Express", TrainClass.VANDE_BHARAT),
            ("EMU", "Delhi-Panipat EMU", TrainClass.EMU),
            ("MEMU", "Local MEMU", TrainClass.MEMU),
            ("Goods", "Freight", TrainClass.FREIGHT),
            ("Passenger", "Slow Passenger", TrainClass.PASSENGER),
            (None, None, TrainClass.UNKNOWN),
        ],
    )
    def test_free_text_types_are_normalised(self, type_, name, expected):
        assert classify_train(type_, name) == expected

    def test_rajdhani_beats_the_generic_express_keyword(self):
        assert classify_train("Express", "Mumbai Rajdhani Express") is TrainClass.RAJDHANI


class TestRailRadarProvider:
    @respx.mock
    async def test_two_boards_produce_a_directional_sighting(self, ctx, now):
        t_prev = (now + timedelta(minutes=6)).isoformat()
        t_next = (now + timedelta(minutes=14)).isoformat()
        respx.get(f"{BASE}/stations/BHD/live").mock(
            return_value=httpx.Response(
                200, json=_envelope([_board_entry("12011", "Kalka Shatabdi",
                                                  "Shatabdi Express", 20.0, t_prev)])
            )
        )
        respx.get(f"{BASE}/stations/KHKN/live").mock(
            return_value=httpx.Response(
                200, json=_envelope([_board_entry("12011", "Kalka Shatabdi",
                                                  "Shatabdi Express", 23.3, t_next)])
            )
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        sightings = await provider.fetch_sightings(ctx)
        await provider.close()

        assert len(sightings) == 1
        s = sightings[0]
        assert s.direct_direction is Direction.UP
        assert s.train_class is TrainClass.SHATABDI
        # Crossing is 1.2 km past Badli in a 3.3 km segment → ~36 % of the way.
        assert now + timedelta(minutes=8) < s.direct_pass_estimate < now + timedelta(minutes=10)

    @respx.mock
    async def test_reverse_chainage_yields_a_down_train(self, ctx, now):
        t_prev = (now + timedelta(minutes=14)).isoformat()
        t_next = (now + timedelta(minutes=6)).isoformat()
        respx.get(f"{BASE}/stations/BHD/live").mock(
            return_value=httpx.Response(
                200, json=_envelope([_board_entry("12012", "Down", "Express", 23.3, t_prev)])
            )
        )
        respx.get(f"{BASE}/stations/KHKN/live").mock(
            return_value=httpx.Response(
                200, json=_envelope([_board_entry("12012", "Down", "Express", 20.0, t_next)])
            )
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        sightings = await provider.fetch_sightings(ctx)
        await provider.close()
        assert sightings[0].direct_direction is Direction.DOWN

    @respx.mock
    async def test_a_train_seen_at_only_one_end_is_skipped(self, ctx, now):
        t = (now + timedelta(minutes=6)).isoformat()
        respx.get(f"{BASE}/stations/BHD/live").mock(
            return_value=httpx.Response(
                200, json=_envelope([_board_entry("99999", "Terminating", "Express", 20.0, t)])
            )
        )
        respx.get(f"{BASE}/stations/KHKN/live").mock(
            return_value=httpx.Response(200, json=_envelope([]))
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        assert await provider.fetch_sightings(ctx) == []
        await provider.close()

    @respx.mock
    async def test_rate_limit_raises_a_typed_error(self, ctx):
        respx.get(f"{BASE}/stations/BHD/live").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "30"}, json={})
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        with pytest.raises(ProviderRateLimited):
            await provider.fetch_sightings(ctx)
        await provider.close()

    @respx.mock
    async def test_bad_credentials_are_not_retryable(self, ctx):
        respx.get(f"{BASE}/stations/BHD/live").mock(return_value=httpx.Response(401, json={}))
        provider = RailRadarProvider(api_key="bad", base_url=BASE)
        with pytest.raises(ProviderError) as exc:
            await provider.fetch_sightings(ctx)
        assert exc.value.retryable is False
        await provider.close()

    @respx.mock
    async def test_malformed_json_is_rejected_cleanly(self, ctx):
        respx.get(f"{BASE}/stations/BHD/live").mock(
            return_value=httpx.Response(200, content=b"<html>maintenance</html>")
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        with pytest.raises(ProviderError):
            await provider.fetch_sightings(ctx)
        await provider.close()

    @respx.mock
    async def test_unexpected_shape_is_rejected(self, ctx):
        respx.get(f"{BASE}/stations/BHD/live").mock(
            return_value=httpx.Response(200, json={"success": True,
                                                   "data": {"trains": "not-a-list"}})
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        with pytest.raises(ProviderError):
            await provider.fetch_sightings(ctx)
        await provider.close()

    @respx.mock
    async def test_network_failure_becomes_provider_unavailable(self, ctx):
        respx.get(f"{BASE}/stations/BHD/live").mock(
            side_effect=httpx.ConnectError("no route to host")
        )
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        with pytest.raises(ProviderUnavailable):
            await provider.fetch_sightings(ctx)
        await provider.close()

    @respx.mock
    async def test_budget_exhaustion_stops_spending(self, ref, now):
        clock = FrozenClock(now)
        budget = ApiBudget(daily_limit=1, clock=clock)
        budget.spend()
        ctx = FetchContext(crossing=ref, now=now, budget=budget, live_call_allowance=0)
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        with pytest.raises(ProviderError):
            await provider.fetch_sightings(ctx)
        await provider.close()

    def test_live_train_payload_parses_into_a_rich_sighting(self, now):
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        data = {
            "trainNumber": "12919",
            "trainName": "Malwa SF Express",
            "status": "running",
            "delayMinutes": 12,
            "lastUpdatedAt": now.isoformat(),
            "train": {"type": "Superfast Express", "avgSpeed": 57.2},
            "currentLocation": {"stationCode": "BHD", "sequence": 2,
                                "segmentProgress": 0.45, "speedKmh": 65.5,
                                "isActualPosition": True},
            "route": [
                {"sequence": 1, "stationCode": "BHD", "distance": 20.0, "isHalt": True,
                 "scheduledDeparture": now.isoformat(), "actualDeparture": now.isoformat(),
                 "status": "departed", "speedToNextStationKmph": 60},
                {"sequence": 2, "stationCode": "KHKN", "distance": 23.3, "isHalt": True,
                 "scheduledArrival": (now + timedelta(minutes=6)).isoformat(),
                 "status": "upcoming"},
            ],
        }
        sighting = provider.parse_live_train(data, now)
        assert sighting is not None
        assert sighting.train_class is TrainClass.SUPERFAST
        assert sighting.position and sighting.position.is_actual
        assert len(sighting.route) == 2

    def test_live_train_payload_without_a_number_is_discarded(self, now):
        provider = RailRadarProvider(api_key="k", base_url=BASE)
        assert provider.parse_live_train({"trainName": "?"}, now) is None


class TestGenericRestProvider:
    @respx.mock
    async def test_configurable_field_map_parses_a_foreign_shape(self, ctx, now):
        respx.get("https://other.test/stations/BHD/live").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"trains": [
                    {"train": {"number": "11111", "name": "Some Express",
                               "type": "Express"},
                     "live": {"expectedDepartureTime":
                              (now + timedelta(minutes=20)).isoformat(),
                              "delayMinutes": 5, "direction": "up"}}
                ]}},
            )
        )
        provider = GenericRestProvider(base_url="https://other.test")
        sightings = await provider.fetch_sightings(ctx)
        await provider.close()
        assert len(sightings) == 1
        assert sightings[0].delay_minutes == 5
        assert sightings[0].direct_direction is Direction.UP

    @respx.mock
    async def test_records_outside_the_horizon_are_dropped(self, ctx, now):
        respx.get("https://other.test/stations/BHD/live").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"trains": [
                    {"train": {"number": "22222", "name": "Late", "type": "Express"},
                     "live": {"expectedDepartureTime":
                              (now + timedelta(hours=9)).isoformat()}}
                ]}},
            )
        )
        provider = GenericRestProvider(base_url="https://other.test")
        assert await provider.fetch_sightings(ctx) == []
        await provider.close()


class TestTimetableProvider:
    async def test_returns_scheduled_trains_from_the_local_database(
        self, session, crossing, now
    ):
        from app.db.session import session_scope

        provider = TimetableProvider(session_scope=session_scope)
        session.commit()
        ctx = FetchContext(crossing=crossing, now=now, horizon_minutes=240)
        sightings = await provider.fetch_sightings(ctx)
        assert sightings, "seeded timetable should yield trains on a Tuesday morning"
        assert all(s.provider == "timetable" for s in sightings)
        assert all(s.direct_pass_estimate is not None for s in sightings)

    async def test_health_does_not_require_the_network(self, session, crossing):
        from app.db.session import session_scope

        provider = TimetableProvider(session_scope=session_scope)
        assert (await provider.health()).healthy


class TestMockProvider:
    async def test_is_deterministic(self, ctx):
        provider = MockProvider()
        first = await provider.fetch_sightings(ctx)
        second = await provider.fetch_sightings(ctx)
        assert [s.train_number for s in first] == [s.train_number for s in second]
        assert first


class TestTolerantParsing:
    """Upstream APIs omit fields, change types and occasionally send "null" as a
    string. These helpers must degrade to a default rather than raise, because
    one bad field should not cost us a whole train."""

    def test_dig_walks_nested_dicts_and_survives_gaps(self):
        from app.providers.parsing import dig

        payload = {"data": {"train": {"number": "12011"}}}
        assert dig(payload, "data", "train", "number") == "12011"
        assert dig(payload, "data", "missing", "number") is None
        assert dig(payload, "data", "train", "name", default="?") == "?"
        assert dig(None, "data") is None

    @pytest.mark.parametrize(
        "value, expected",
        [("42.5", 42.5), (42, 42.0), (None, None), ("abc", None), (True, None), ([], None)],
    )
    def test_as_float(self, value, expected):
        from app.providers.parsing import as_float

        assert as_float(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [("7", 7), (7.9, 7), (None, 0), ("", 0), (True, 0), ({}, 0)],
    )
    def test_as_int(self, value, expected):
        from app.providers.parsing import as_int

        assert as_int(value) == expected

    def test_as_str_treats_blank_as_missing(self):
        from app.providers.parsing import as_str

        assert as_str("  BHD  ") == "BHD"
        assert as_str("   ") is None
        assert as_str(None, "fallback") == "fallback"

    def test_as_bool_accepts_the_usual_suspects(self):
        from app.providers.parsing import as_bool

        assert as_bool(True) is True
        assert as_bool("true") is True
        assert as_bool("1") is True
        assert as_bool("no") is False
        assert as_bool(None, default=True) is True

    def test_parse_datetime_handles_offsets_and_trailing_z(self):
        from app.providers.parsing import parse_datetime

        with_offset = parse_datetime("2026-07-21T08:00:00+05:30")
        assert with_offset is not None and with_offset.utcoffset().total_seconds() == 19800
        # Python 3.10's fromisoformat rejects "Z"; we normalise it.
        assert parse_datetime("2026-07-21T02:30:00Z") is not None
        assert parse_datetime("not a date") is None
        assert parse_datetime(None) is None

    def test_parse_clock_time_builds_an_ist_instant_on_the_given_day(self):
        from datetime import date

        from app.providers.parsing import parse_clock_time

        parsed = parse_clock_time("23:55", date(2026, 7, 21))
        assert parsed is not None
        assert (parsed.hour, parsed.minute) == (23, 55)
        assert parse_clock_time("99:99", date(2026, 7, 21)) is None
        assert parse_clock_time("", date(2026, 7, 21)) is None

    def test_clock_times_past_midnight_roll_into_the_next_day(self):
        """Indian timetables legitimately print 25:10 for a 01:10 departure."""
        from datetime import date

        from app.providers.parsing import parse_clock_time

        parsed = parse_clock_time("25:10", date(2026, 7, 21))
        assert parsed is not None
        assert parsed.day == 22 and parsed.hour == 1
