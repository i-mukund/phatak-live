"""Crowd report guards.

The endpoint is unauthenticated and writes to a shared model, so most of these
tests assert that it *declines* — and the last group asserts the property that
actually matters: abuse cannot move a countdown.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.db.models import ClosureWindow, GateReport, Observation
from app.services.report_service import ReportOutcome, ReportService


@pytest.fixture
def service(settings) -> ReportService:
    return ReportService(settings=get_settings())


def add_window(session, crossing_id, start, end):
    session.add(
        ClosureWindow(
            crossing_id=crossing_id, close_at=start, open_at=end,
            source="predicted", confidence=0.9, is_superseded=False,
        )
    )
    session.flush()


class TestDeduplication:
    def test_first_report_is_accepted(self, session, crossing_row, service, now):
        r = service.submit(session, crossing_row, "closed", now, client_id="abc")
        assert r.accepted is True
        assert r.next_report_at == now + timedelta(seconds=600)
        assert session.query(GateReport).count() == 1

    def test_same_client_tapping_again_is_a_duplicate(
        self, session, crossing_row, service, now
    ):
        service.submit(session, crossing_row, "closed", now, client_id="abc")
        session.flush()
        again = service.submit(
            session, crossing_row, "closed", now + timedelta(seconds=30), client_id="abc"
        )
        assert again.accepted is False
        assert again.outcome is ReportOutcome.DUPLICATE
        assert session.query(GateReport).count() == 1, "no second row written"

    def test_same_client_may_report_again_after_the_cooldown(
        self, session, crossing_row, service, now
    ):
        service.submit(session, crossing_row, "closed", now, client_id="abc")
        session.flush()
        later = service.submit(
            session, crossing_row, "closed", now + timedelta(minutes=11), client_id="abc"
        )
        assert later.accepted is True

    def test_a_different_client_is_not_blocked(self, session, crossing_row, service, now):
        service.submit(session, crossing_row, "closed", now, client_id="abc")
        session.flush()
        other = service.submit(
            session, crossing_row, "closed", now + timedelta(seconds=30), client_id="xyz"
        )
        assert other.accepted is True

    def test_the_client_id_is_never_stored_raw(self, session, crossing_row, service, now):
        service.submit(session, crossing_row, "closed", now, client_id="secret-id")
        session.flush()
        report = session.query(GateReport).one()
        assert report.client_hash != "secret-id"
        assert len(report.client_hash) == 64


class TestRateLimiting:
    def test_ip_ceiling_stops_identity_churn(self, session, crossing_row, service, now):
        """Clearing storage mints a new client id, so the IP cap is the
        backstop."""
        for i in range(12):
            service.submit(
                session, crossing_row, "closed", now + timedelta(minutes=i),
                client_id=f"fresh-{i}", client_ip="203.0.113.9",
            )
            session.flush()
        blocked = service.submit(
            session, crossing_row, "closed", now + timedelta(minutes=13),
            client_id="fresh-99", client_ip="203.0.113.9",
        )
        assert blocked.accepted is False
        assert blocked.outcome is ReportOutcome.RATE_LIMITED

    def test_a_different_ip_is_unaffected(self, session, crossing_row, service, now):
        for i in range(12):
            service.submit(
                session, crossing_row, "closed", now + timedelta(minutes=i),
                client_id=f"a-{i}", client_ip="203.0.113.9",
            )
            session.flush()
        other = service.submit(
            session, crossing_row, "closed", now, client_id="b", client_ip="198.51.100.4"
        )
        assert other.accepted is True


class TestInterpretation:
    def test_a_report_matching_a_predicted_closure_corroborates(
        self, session, crossing_row, service, now
    ):
        add_window(session, crossing_row.id, now - timedelta(minutes=1), now + timedelta(minutes=3))
        r = service.submit(session, crossing_row, "closed", now, client_id="abc")

        assert r.outcome is ReportOutcome.CORROBORATED
        obs = session.query(Observation).one()
        assert obs.is_unexplained is False

    def test_an_unpredicted_closure_becomes_the_freight_signal(
        self, session, crossing_row, service, now
    ):
        """Nothing we know about closed this gate — that is what the button is
        actually for."""
        r = service.submit(session, crossing_row, "closed", now, client_id="abc")

        assert r.outcome is ReportOutcome.UNEXPLAINED
        obs = session.query(Observation).one()
        assert obs.is_unexplained is True

    def test_unexplained_reports_raise_the_freight_risk_band(
        self, session, crossing_row, service, now, settings
    ):
        from app.services.learning.engine import LearningEngine

        for i in range(6):
            service.submit(
                session, crossing_row, "closed", now + timedelta(minutes=i * 11),
                client_id=f"c-{i}",
            )
            session.flush()
        risk = LearningEngine().freight_risk(session, crossing_row.id, now)
        assert risk > 0.0, "crowd reports must actually reach the freight estimate"

    def test_corroborations_count_distinct_clients_not_taps(
        self, session, crossing_row, service, now
    ):
        for cid in ("a", "b", "c"):
            service.submit(session, crossing_row, "closed", now, client_id=cid)
            session.flush()
        latest = session.query(Observation).order_by(Observation.id.desc()).first()
        assert latest.detail["corroborations"] == 3

    def test_an_open_report_is_recorded_but_never_flagged_as_freight(
        self, session, crossing_row, service, now
    ):
        r = service.submit(session, crossing_row, "open", now, client_id="abc")
        assert r.outcome is ReportOutcome.RECORDED
        assert session.query(Observation).one().is_unexplained is False


class TestBlastRadius:
    """The property that makes abuse uninteresting."""

    def test_crowd_reports_cannot_move_a_calibration_offset(
        self, session, crossing_row, service, now
    ):
        from app.services.learning.engine import LearningEngine

        learning = LearningEngine()
        before = learning.load_calibration(session, crossing_row.id).by_class

        for i in range(40):
            service.submit(
                session, crossing_row, "closed", now + timedelta(minutes=i * 11),
                client_id=f"attacker-{i}",
            )
            session.flush()
        learning.grade_pending(session, crossing_row.id, now + timedelta(hours=9))

        after = learning.load_calibration(session, crossing_row.id).by_class
        assert after == before, "timing offsets must be driven only by provider actuals"
