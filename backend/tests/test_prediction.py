"""Prediction engine tests.

The engine is a pure function, so every scenario here is a table of inputs and
an assertion — no mocks, no clock patching, no database.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain import Direction, TrainClass
from app.services.prediction.calibration import Calibration, CalibrationSet
from app.services.prediction.engine import (
    PredictionEngine,
    gate_clear_seconds,
    gate_close_lead_seconds,
    merge_windows,
)
from app.services.prediction.geometry import resolve_transit
from app.services.prediction.model import ClosureWindow, Estimator, GateState
from tests.factories import direct_sighting, route_sighting


@pytest.fixture
def engine() -> PredictionEngine:
    return PredictionEngine(
        blend_horizon_km=12.0,
        default_speed_kmph=50.0,
        max_sighting_age_seconds=900,
        horizon_minutes=120,
    )


class TestGatePhysics:
    def test_faster_trains_get_shorter_lead_times(self):
        slow = gate_close_lead_seconds(
            approach_distance_km=2.5, speed_kmph=40, minimum=60, maximum=900
        )
        fast = gate_close_lead_seconds(
            approach_distance_km=2.5, speed_kmph=100, minimum=60, maximum=900
        )
        assert slow > fast
        assert fast == pytest.approx(90.0, abs=1)

    def test_lead_time_is_clamped_both_ways(self):
        assert gate_close_lead_seconds(
            approach_distance_km=2.5, speed_kmph=5, minimum=120, maximum=600
        ) == 600
        assert gate_close_lead_seconds(
            approach_distance_km=0.1, speed_kmph=120, minimum=120, maximum=600
        ) == 120

    def test_longer_trains_take_longer_to_clear(self):
        short = gate_clear_seconds(train_length_m=250, speed_kmph=60, operator_lag_seconds=75)
        long = gate_clear_seconds(train_length_m=700, speed_kmph=60, operator_lag_seconds=75)
        assert long > short > 75


class TestGeometry:
    def test_direction_up_when_prev_precedes_next(self, ref, now):
        transit = resolve_transit(ref, route_sighting(now=now), now)
        assert transit is not None
        assert transit.direction is Direction.UP

    def test_direction_down_when_route_is_reversed(self, ref, now):
        transit = resolve_transit(ref, route_sighting(now=now, reverse=True), now)
        assert transit is not None
        assert transit.direction is Direction.DOWN

    def test_train_on_another_line_is_ignored(self, ref, now):
        sighting = route_sighting(now=now, prev_code="XXX", next_code="YYY")
        assert resolve_transit(ref, sighting, now) is None

    def test_pass_time_lands_between_the_bracketing_stations(self, ref, now):
        sighting = route_sighting(now=now, minutes_to_prev=6, minutes_to_next=14)
        transit = resolve_transit(ref, sighting, now)
        assert transit is not None
        assert now + timedelta(minutes=6) < transit.pass_at < now + timedelta(minutes=14)

    def test_delay_is_applied_once_when_no_actuals_exist(self, ref, now):
        on_time = resolve_transit(ref, route_sighting(now=now), now)
        late = resolve_transit(ref, route_sighting(now=now, delay_minutes=20), now)
        assert on_time and late
        delta = (late.pass_at - on_time.pass_at).total_seconds()
        assert delta == pytest.approx(1200, abs=30)

    def test_delay_is_not_double_counted_when_actual_times_are_present(self, ref, now):
        """Actual timings already contain the delay — adding it again is the
        classic 15-minute bug."""
        with_actuals = resolve_transit(
            ref, route_sighting(now=now, delay_minutes=20, with_actuals=True), now
        )
        without = resolve_transit(
            ref, route_sighting(now=now, delay_minutes=0, with_actuals=True), now
        )
        assert with_actuals and without
        assert with_actuals.pass_at == without.pass_at

    def test_absurd_speeds_are_rejected_in_favour_of_a_sane_default(self, ref, now):
        transit = resolve_transit(ref, route_sighting(now=now, speed_kmph=999.0), now)
        assert transit is not None
        assert 8.0 <= transit.speed_kmph <= 180.0

    def test_timetable_sighting_falls_back_to_the_direct_estimator(self, ref, now):
        transit = resolve_transit(ref, direct_sighting(now=now, minutes_ahead=25), now)
        assert transit is not None
        assert transit.estimator is Estimator.DIRECT
        assert transit.pass_at == now + timedelta(minutes=25)

    def test_interpolated_position_is_trusted_less_than_an_observed_one(self, ref, now):
        observed = resolve_transit(
            ref, route_sighting(now=now, is_actual=True, progress=0.9), now
        )
        interpolated = resolve_transit(
            ref, route_sighting(now=now, is_actual=False, progress=0.9), now
        )
        assert observed and interpolated
        assert observed.is_actual_position and not interpolated.is_actual_position


class TestWindowMerging:
    def _window(self, now, start_min, end_min):
        return ClosureWindow(
            close_at=now + timedelta(minutes=start_min),
            open_at=now + timedelta(minutes=end_min),
            confidence=0.8,
        )

    def test_near_adjacent_closures_become_one(self, now):
        merged = merge_windows(
            [self._window(now, 0, 5), self._window(now, 7, 12)], min_gate_cycle_seconds=210
        )
        assert len(merged) == 1
        assert merged[0].duration_seconds == 12 * 60

    def test_well_separated_closures_stay_separate(self, now):
        merged = merge_windows(
            [self._window(now, 0, 5), self._window(now, 30, 35)], min_gate_cycle_seconds=210
        )
        assert len(merged) == 2

    def test_merged_confidence_is_the_weakest_contributor(self, now):
        a = ClosureWindow(now, now + timedelta(minutes=5), confidence=0.9)
        b = ClosureWindow(
            now + timedelta(minutes=6), now + timedelta(minutes=10), confidence=0.4
        )
        merged = merge_windows([a, b], min_gate_cycle_seconds=210)
        assert merged[0].confidence == 0.4


class TestPredictionEngine:
    def test_open_when_nothing_is_coming(self, engine, ref, now):
        prediction = engine.predict(crossing=ref, sightings=[], now=now)
        assert prediction.state is GateState.OPEN
        assert prediction.windows == ()
        assert prediction.confidence.score > 0

    def test_closed_while_a_train_is_at_the_gate(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref,
            sightings=[direct_sighting(now=now, minutes_ahead=0.2)],
            now=now,
        )
        assert prediction.state is GateState.CLOSED
        assert prediction.seconds_until_open is not None

    def test_closing_soon_within_five_minutes(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref,
            sightings=[direct_sighting(now=now, minutes_ahead=6)],
            now=now,
        )
        assert prediction.state is GateState.CLOSING_SOON

    def test_two_trains_close_together_produce_one_window(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref,
            sightings=[
                direct_sighting(now=now, minutes_ahead=30, number="A"),
                direct_sighting(now=now, minutes_ahead=33, number="B"),
            ],
            now=now,
        )
        assert len(prediction.windows) == 1
        assert len(prediction.windows[0].causes) == 2

    def test_two_distant_trains_produce_two_windows(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref,
            sightings=[
                direct_sighting(now=now, minutes_ahead=20, number="A"),
                direct_sighting(now=now, minutes_ahead=70, number="B"),
            ],
            now=now,
        )
        assert len(prediction.windows) == 2

    def test_stale_sightings_are_discarded_and_reported(self, engine, ref, now):
        stale = direct_sighting(now=now - timedelta(hours=2), minutes_ahead=40)
        prediction = engine.predict(crossing=ref, sightings=[stale], now=now)
        assert prediction.windows == ()
        assert any("stale" in note for note in prediction.notes)

    def test_trains_beyond_the_horizon_are_ignored(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref, sightings=[direct_sighting(now=now, minutes_ahead=300)], now=now
        )
        assert prediction.windows == ()

    def test_cancelled_trains_do_not_close_the_gate(self, engine, ref, now):
        from dataclasses import replace

        from app.domain import RunStatus

        cancelled = replace(
            direct_sighting(now=now, minutes_ahead=20), status=RunStatus.CANCELLED
        )
        prediction = engine.predict(crossing=ref, sightings=[cancelled], now=now)
        assert prediction.windows == ()

    def test_freight_gets_a_longer_closure_than_an_emu(self, engine, ref, now):
        emu = engine.predict(
            crossing=ref,
            sightings=[direct_sighting(now=now, minutes_ahead=30,
                                       train_class=TrainClass.EMU, speed_kmph=55)],
            now=now,
        )
        freight = engine.predict(
            crossing=ref,
            sightings=[direct_sighting(now=now, minutes_ahead=30,
                                       train_class=TrainClass.FREIGHT, speed_kmph=35)],
            now=now,
        )
        assert freight.windows[0].duration_seconds > emu.windows[0].duration_seconds

    def test_calibration_shifts_the_window(self, engine, ref, now):
        base = engine.predict(
            crossing=ref, sightings=[direct_sighting(now=now, minutes_ahead=30)], now=now
        )
        calibrated = engine.predict(
            crossing=ref,
            sightings=[direct_sighting(now=now, minutes_ahead=30)],
            now=now,
            calibration=CalibrationSet(
                by_class={"emu": Calibration(pass_offset_seconds=120, sample_count=20)}
            ),
        )
        shift = (
            calibrated.windows[0].close_at - base.windows[0].close_at
        ).total_seconds()
        assert shift == pytest.approx(120, abs=1)

    def test_calibration_can_never_invert_a_window(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref,
            sightings=[direct_sighting(now=now, minutes_ahead=30)],
            now=now,
            calibration=CalibrationSet(
                by_class={
                    "emu": Calibration(
                        close_offset_seconds=600, open_offset_seconds=-600, sample_count=50
                    )
                }
            ),
        )
        assert prediction.windows[0].open_at > prediction.windows[0].close_at

    def test_degraded_data_lowers_confidence(self, engine, ref, now):
        healthy = engine.predict(
            crossing=ref, sightings=[route_sighting(now=now)], now=now, degraded=False
        )
        degraded = engine.predict(
            crossing=ref, sightings=[route_sighting(now=now)], now=now, degraded=True
        )
        assert degraded.confidence.score < healthy.confidence.score

    def test_confidence_never_claims_certainty(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref,
            sightings=[route_sighting(now=now, minutes_to_prev=1, minutes_to_next=3)],
            now=now,
            calibration=CalibrationSet(
                by_class={"default": Calibration(sample_count=500, pass_mae_seconds=0.0)}
            ),
        )
        assert prediction.confidence.score <= 0.97

    def test_safe_to_leave_answers_the_product_question(self, engine, ref, now):
        prediction = engine.predict(
            crossing=ref, sightings=[direct_sighting(now=now, minutes_ahead=8)], now=now
        )
        assert prediction.safe_to_leave(60) is True       # arrive before it shuts
        assert prediction.safe_to_leave(8 * 60) is False  # arrive as it shuts
