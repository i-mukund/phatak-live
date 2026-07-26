"""Learning engine tests: does the thing actually get better?"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.db.models import Observation, ObservationSource, PredictionRecord
from app.services.learning.engine import LearningEngine
from app.services.prediction.engine import PredictionEngine
from tests.factories import direct_sighting, route_sighting


@pytest.fixture
def learning() -> LearningEngine:
    return LearningEngine()


@pytest.fixture
def prediction(now, crossing):
    return PredictionEngine().predict(
        crossing=crossing,
        sightings=[direct_sighting(now=now, minutes_ahead=20, number="12011")],
        now=now,
    )


class TestRecording:
    def test_predictions_are_persisted(self, session, learning, crossing_row, prediction):
        assert learning.record_predictions(session, crossing_row.id, prediction) == 1
        assert session.query(PredictionRecord).count() == 1

    def test_repeated_ticks_do_not_duplicate_the_same_train(
        self, session, learning, crossing_row, prediction
    ):
        learning.record_predictions(session, crossing_row.id, prediction)
        session.flush()
        assert learning.record_predictions(session, crossing_row.id, prediction) == 0
        assert session.query(PredictionRecord).count() == 1

    def test_actual_times_at_both_stations_become_ground_truth(
        self, session, learning, crossing, now
    ):
        sighting = route_sighting(now=now, with_actuals=True, minutes_to_prev=-10,
                                  minutes_to_next=-2)
        assert learning.derive_observations(session, crossing, [sighting]) == 1
        obs = session.query(Observation).one()
        assert obs.source == ObservationSource.PROVIDER_ACTUALS.value
        assert obs.observed_pass_at is not None

    def test_observations_are_not_duplicated(self, session, learning, crossing, now):
        sighting = route_sighting(now=now, with_actuals=True)
        learning.derive_observations(session, crossing, [sighting])
        session.flush()
        assert learning.derive_observations(session, crossing, [sighting]) == 0

    def test_a_train_without_actuals_produces_no_observation(
        self, session, learning, crossing, now
    ):
        assert learning.derive_observations(
            session, crossing, [route_sighting(now=now, with_actuals=False)]
        ) == 0

    def test_a_user_report_is_stored_as_both_report_and_observation(
        self, session, learning, crossing_row, now
    ):
        report = learning.record_user_report(session, crossing_row.id, "closed", now)
        assert report.id is not None
        obs = session.query(Observation).one()
        assert obs.source == ObservationSource.USER_REPORT.value
        assert obs.observed_close_at == now


class TestGrading:
    def _seed_pair(self, session, learning, crossing_row, now, error_seconds: float):
        predicted_pass = now - timedelta(minutes=30)
        session.add(
            PredictionRecord(
                crossing_id=crossing_row.id,
                train_number="12011",
                train_class="shatabdi",
                provider="test",
                predicted_at=now - timedelta(minutes=60),
                predicted_pass_at=predicted_pass,
                predicted_close_at=predicted_pass - timedelta(minutes=3),
                predicted_open_at=predicted_pass + timedelta(minutes=2),
                horizon_seconds=1800,
                confidence=0.8,
            )
        )
        session.add(
            Observation(
                crossing_id=crossing_row.id,
                train_number="12011",
                train_class="shatabdi",
                source=ObservationSource.PROVIDER_ACTUALS.value,
                observed_pass_at=predicted_pass + timedelta(seconds=error_seconds),
            )
        )
        session.flush()

    def test_grading_computes_the_signed_error(self, session, learning, crossing_row, now):
        self._seed_pair(session, learning, crossing_row, now, 90)
        assert learning.grade_pending(session, crossing_row.id, now) == 1
        record = session.query(PredictionRecord).one()
        assert record.graded is True
        assert record.pass_error_seconds == pytest.approx(90, abs=1)

    def test_grading_updates_both_the_class_and_default_profiles(
        self, session, learning, crossing_row, now
    ):
        self._seed_pair(session, learning, crossing_row, now, 120)
        learning.grade_pending(session, crossing_row.id, now)
        calibration = learning.load_calibration(session, crossing_row.id)
        assert calibration.by_class["shatabdi"].sample_count == 1
        assert calibration.by_class["default"].sample_count == 1
        assert calibration.by_class["shatabdi"].pass_offset_seconds > 0

    def test_repeated_late_trains_pull_the_offset_toward_the_truth(
        self, session, learning, crossing_row, now
    ):
        for i in range(12):
            moment = now - timedelta(minutes=30 * (i + 1))
            session.add(
                PredictionRecord(
                    crossing_id=crossing_row.id,
                    train_number=f"T{i}",
                    train_class="express",
                    provider="test",
                    predicted_at=moment - timedelta(minutes=20),
                    predicted_pass_at=moment,
                    predicted_close_at=moment - timedelta(minutes=3),
                    predicted_open_at=moment + timedelta(minutes=2),
                    horizon_seconds=1200,
                    confidence=0.8,
                )
            )
            session.add(
                Observation(
                    crossing_id=crossing_row.id,
                    train_number=f"T{i}",
                    train_class="express",
                    observed_pass_at=moment + timedelta(seconds=180),
                )
            )
        session.flush()
        learning.grade_pending(session, crossing_row.id, now)

        offset = learning.load_calibration(
            session, crossing_row.id
        ).by_class["express"].pass_offset_seconds
        assert 100 < offset <= 180, "EWMA should converge toward the 180 s bias"

    def test_implausible_residuals_are_discarded(self, session, learning, crossing_row, now):
        self._seed_pair(session, learning, crossing_row, now, 60 * 60 * 3)
        learning.grade_pending(session, crossing_row.id, now)
        assert session.query(PredictionRecord).one().pass_error_seconds is None
        assert learning.load_calibration(session, crossing_row.id).by_class == {}

    def test_ungraded_predictions_are_abandoned_rather_than_queued_forever(
        self, session, learning, crossing_row, now
    ):
        session.add(
            PredictionRecord(
                crossing_id=crossing_row.id,
                train_number="99999",
                train_class="express",
                provider="test",
                predicted_at=now - timedelta(hours=4),
                predicted_pass_at=now - timedelta(hours=3),
                predicted_close_at=now - timedelta(hours=3, minutes=3),
                predicted_open_at=now - timedelta(hours=2, minutes=58),
                horizon_seconds=3600,
                confidence=0.7,
            )
        )
        session.flush()
        learning.grade_pending(session, crossing_row.id, now)
        assert session.query(PredictionRecord).one().graded is True

    def test_accuracy_summary_reports_useful_statistics(
        self, session, learning, crossing_row, now
    ):
        self._seed_pair(session, learning, crossing_row, now, 45)
        learning.grade_pending(session, crossing_row.id, now)
        summary = learning.accuracy_summary(session, crossing_row.id, now)
        assert summary["samples"] == 1
        assert summary["within_2min_pct"] == 100.0


class TestCalibrationFeedback:
    def test_a_learned_offset_changes_the_next_prediction(
        self, session, learning, crossing_row, crossing, now
    ):
        engine = PredictionEngine()
        before = engine.predict(
            crossing=crossing,
            sightings=[direct_sighting(now=now, minutes_ahead=30)],
            now=now,
        )

        predicted_pass = now - timedelta(minutes=30)
        for i in range(6):
            session.add(
                PredictionRecord(
                    crossing_id=crossing_row.id,
                    train_number=f"E{i}",
                    train_class="emu",
                    provider="test",
                    predicted_at=predicted_pass - timedelta(minutes=20),
                    predicted_pass_at=predicted_pass - timedelta(minutes=i),
                    predicted_close_at=predicted_pass - timedelta(minutes=i + 3),
                    predicted_open_at=predicted_pass - timedelta(minutes=i - 2),
                    horizon_seconds=1200,
                    confidence=0.8,
                )
            )
            session.add(
                Observation(
                    crossing_id=crossing_row.id,
                    train_number=f"E{i}",
                    train_class="emu",
                    observed_pass_at=predicted_pass - timedelta(minutes=i) +
                    timedelta(seconds=240),
                )
            )
        session.flush()
        learning.grade_pending(session, crossing_row.id, now)

        after = engine.predict(
            crossing=crossing,
            sightings=[direct_sighting(now=now, minutes_ahead=30)],
            now=now,
            calibration=learning.load_calibration(session, crossing_row.id),
        )
        assert after.windows[0].close_at > before.windows[0].close_at
