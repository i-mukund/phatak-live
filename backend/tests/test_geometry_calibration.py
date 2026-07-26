"""Autonomous geometry calibration tests.

The calibrator automates docs/TROUBLESHOOTING.md §"predictions are consistently
early or late". The dangerous failure mode is acting when it should not, so
half of these tests assert *inaction*.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db.models import CalibrationProfile, GeometryAdjustment, PredictionRecord
from app.services.learning.geometry import GeometryCalibrator


@pytest.fixture
def calibrator() -> GeometryCalibrator:
    return GeometryCalibrator(
        min_samples_per_direction=10,
        min_bias_seconds=45.0,
        min_delta_km=0.1,
        max_step_km=0.35,
        cooldown_days=3,
    )


def seed_residuals(
    session,
    crossing_id: int,
    now: datetime,
    *,
    bias_up: float,
    bias_down: float,
    n: int = 12,
    speed: float = 60.0,
) -> None:
    """Graded predictions with the given median residual per direction."""
    for direction, bias in (("up", bias_up), ("down", bias_down)):
        for i in range(n):
            moment = now - timedelta(hours=i + 1)
            jitter = (i % 3 - 1) * 5.0  # small spread; median stays at `bias`
            session.add(
                PredictionRecord(
                    crossing_id=crossing_id,
                    train_number=f"{direction[:1].upper()}{i}",
                    train_class="express",
                    direction=direction,
                    speed_kmph=speed,
                    provider="test",
                    predicted_at=moment - timedelta(minutes=20),
                    predicted_pass_at=moment,
                    predicted_close_at=moment - timedelta(minutes=3),
                    predicted_open_at=moment + timedelta(minutes=2),
                    horizon_seconds=1200,
                    confidence=0.8,
                    graded=True,
                    pass_error_seconds=bias + jitter,
                )
            )
    session.flush()


class TestDetection:
    def test_opposite_signed_bias_moves_the_crossing_toward_the_truth(
        self, session, crossing_row, calibrator, now
    ):
        """UP late, DOWN early ⇒ the crossing is further from prev than seeded.
        120 s at 60 km/h ⇒ ~2 km true error, clamped to the 0.35 km step."""
        old_prev = crossing_row.distance_from_prev_km
        old_length = crossing_row.segment_length_km
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0)

        review = calibrator.review(session, crossing_row, now)

        assert review.adjusted is True
        assert crossing_row.distance_from_prev_km > old_prev
        assert review.delta_km == pytest.approx(0.35, abs=0.01)  # clamped
        # The crossing moved *along* the segment; the segment did not stretch.
        assert crossing_row.segment_length_km == pytest.approx(old_length, abs=1e-6)

    def test_the_mirror_signature_moves_it_the_other_way(
        self, session, crossing_row, calibrator, now
    ):
        old_prev = crossing_row.distance_from_prev_km
        seed_residuals(session, crossing_row.id, now, bias_up=-90.0, bias_down=90.0)

        review = calibrator.review(session, crossing_row, now)

        assert review.adjusted is True
        assert crossing_row.distance_from_prev_km < old_prev

    def test_correction_magnitude_tracks_speed(self, session, crossing_row, now):
        """The same 60 s bias means less distance for a slow train."""
        calibrator = GeometryCalibrator(min_samples_per_direction=10, max_step_km=5.0)
        seed_residuals(session, crossing_row.id, now,
                       bias_up=60.0, bias_down=-60.0, speed=48.0)

        review = calibrator.review(session, crossing_row, now)

        # 60 s at 48 km/h = 0.8 km
        assert review.adjusted
        assert review.delta_km == pytest.approx(0.8, abs=0.05)

    def test_adjustment_is_audited_with_its_evidence(
        self, session, crossing_row, calibrator, now
    ):
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0)
        calibrator.review(session, crossing_row, now)

        audit = session.query(GeometryAdjustment).one()
        assert audit.evidence["samples_up"] == 12
        assert audit.evidence["bias_up_seconds"] == pytest.approx(120.0, abs=1)
        assert audit.new_distance_from_prev_km != audit.old_distance_from_prev_km

    def test_absorbed_ewma_offsets_are_decayed_after_correction(
        self, session, crossing_row, calibrator, now
    ):
        """Without the decay the same error would be corrected twice: once in
        the geometry, once in the learned offset."""
        session.add(
            CalibrationProfile(
                crossing_id=crossing_row.id, train_class="express",
                pass_offset_seconds=100.0, sample_count=20,
            )
        )
        session.flush()
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0)

        calibrator.review(session, crossing_row, now)

        profile = session.query(CalibrationProfile).one()
        assert profile.pass_offset_seconds == pytest.approx(25.0, abs=0.1)


class TestRefusalToAct:
    """A calibrator that fires on the wrong signature is worse than none."""

    def test_same_signed_bias_is_timing_not_geometry(
        self, session, crossing_row, calibrator, now
    ):
        old_prev = crossing_row.distance_from_prev_km
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=110.0)

        review = calibrator.review(session, crossing_row, now)

        assert review.adjusted is False
        assert "timing" in review.reason
        assert crossing_row.distance_from_prev_km == old_prev

    def test_too_few_samples_in_either_direction(
        self, session, crossing_row, calibrator, now
    ):
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0, n=5)
        review = calibrator.review(session, crossing_row, now)
        assert review.adjusted is False
        assert review.reason == "insufficient samples"

    def test_small_bias_is_left_to_the_ewma_offsets(
        self, session, crossing_row, calibrator, now
    ):
        seed_residuals(session, crossing_row.id, now, bias_up=20.0, bias_down=-20.0)
        review = calibrator.review(session, crossing_row, now)
        assert review.adjusted is False

    def test_one_absurd_outlier_cannot_fake_the_signature(
        self, session, crossing_row, calibrator, now
    ):
        """Median-based: eleven honest ~0 residuals beat one 30-minute lie."""
        seed_residuals(session, crossing_row.id, now, bias_up=5.0, bias_down=-5.0, n=11)
        session.add(
            PredictionRecord(
                crossing_id=crossing_row.id, train_number="LIAR", train_class="express",
                direction="up", speed_kmph=60.0, provider="test",
                predicted_at=now - timedelta(hours=1),
                predicted_pass_at=now - timedelta(minutes=30),
                predicted_close_at=now - timedelta(minutes=33),
                predicted_open_at=now - timedelta(minutes=28),
                horizon_seconds=1200, confidence=0.8, graded=True,
                pass_error_seconds=1800.0,
            )
        )
        session.flush()
        review = calibrator.review(session, crossing_row, now)
        assert review.adjusted is False

    def test_cooldown_blocks_back_to_back_adjustments(
        self, session, crossing_row, calibrator, now
    ):
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0)
        first = calibrator.review(session, crossing_row, now)
        assert first.adjusted

        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0)
        second = calibrator.review(session, crossing_row, now + timedelta(days=1))
        assert second.adjusted is False
        assert second.reason == "cooldown"

    def test_step_is_bounded_no_matter_how_large_the_bias(
        self, session, crossing_row, calibrator, now
    ):
        seed_residuals(session, crossing_row.id, now, bias_up=900.0, bias_down=-900.0)
        review = calibrator.review(session, crossing_row, now)
        assert review.adjusted
        assert abs(review.delta_km) <= 0.35

    def test_crossing_can_never_be_pushed_past_a_station(
        self, session, crossing_row, now
    ):
        """Repeated corrections converge on the edge margin, not past it."""
        calibrator = GeometryCalibrator(
            min_samples_per_direction=10, max_step_km=10.0, cooldown_days=0
        )
        seed_residuals(session, crossing_row.id, now, bias_up=3600.0, bias_down=-3600.0)
        calibrator.review(session, crossing_row, now)

        assert crossing_row.distance_from_prev_km <= crossing_row.segment_length_km - 0.2
        assert crossing_row.distance_from_next_km >= 0.2

    def test_evidence_from_before_the_last_fix_is_ignored(
        self, session, crossing_row, calibrator, now
    ):
        """Old residuals describe the geometry we already corrected."""
        seed_residuals(session, crossing_row.id, now, bias_up=120.0, bias_down=-120.0)
        calibrator.review(session, crossing_row, now)
        prev_after_first = crossing_row.distance_from_prev_km

        # Beyond cooldown, but with no *new* evidence: nothing should move.
        later = now + timedelta(days=4)
        review = calibrator.review(session, crossing_row, later)
        assert review.adjusted is False
        assert crossing_row.distance_from_prev_km == prev_after_first
