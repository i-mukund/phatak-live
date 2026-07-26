"""Integration tests over the real ASGI app (in-memory transport, real DB)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import session as session_module
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    get_settings.cache_clear()
    session_module.reset_state()
    with TestClient(create_app()) as c:
        yield c
    session_module.reset_state()
    get_settings.cache_clear()


ADMIN = {"X-Admin-Key": "test-admin-key"}


class TestHealth:
    def test_liveness(self, client):
        body = client.get("/health/live").json()
        assert body["status"] == "ok"
        assert body["version"]

    def test_readiness_reports_providers(self, client):
        body = client.get("/health/ready").json()
        assert body["database"] is True
        assert body["providers"]

    def test_metrics_are_exposed(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "phatak_" in response.text

    def test_openapi_document_is_valid(self, client):
        spec = client.get("/openapi.json").json()
        assert "/api/v1/crossings/{slug}/status" in spec["paths"]


class TestCrossings:
    def test_seeded_crossing_is_listed(self, client):
        body = client.get("/api/v1/crossings").json()
        assert [c["slug"] for c in body] == ["siraspur"]

    def test_detail_exposes_the_segment_geometry(self, client):
        body = client.get("/api/v1/crossings/siraspur").json()
        assert body["previous_station"]["code"] == "BHD"
        assert body["next_station"]["code"] == "KHKN"

    def test_unknown_crossing_returns_a_typed_404(self, client):
        response = client.get("/api/v1/crossings/nowhere")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert response.json()["trace_id"]


class TestStatus:
    def test_status_answers_without_any_ingest_having_run(self, client):
        """Cold start must still produce an answer (failure mode F3)."""
        body = client.get("/api/v1/crossings/siraspur/status").json()
        assert body["state"] in {"open", "closed", "closing_soon"}
        assert body["confidence"]["score"] > 0
        assert body["data"]["degraded"] is True

    def test_status_after_ingest_is_not_degraded(self, client):
        assert client.post("/api/v1/admin/ingest", headers=ADMIN).status_code == 200
        body = client.get("/api/v1/crossings/siraspur/status").json()
        assert body["data"]["degraded"] is False
        assert body["data"]["providers_used"]

    def test_timestamps_are_absolute_and_in_ist(self, client):
        client.post("/api/v1/admin/ingest", headers=ADMIN)
        body = client.get("/api/v1/crossings/siraspur/status").json()
        assert body["server_time"].endswith("+05:30")
        window = body["next_closure"] or body["current_closure"]
        if window:
            assert window["close_at"].endswith("+05:30")

    def test_second_request_is_served_from_cache(self, client):
        client.get("/api/v1/crossings/siraspur/status")
        second = client.get("/api/v1/crossings/siraspur/status")
        assert second.headers["X-Cache"] == "hit"

    def test_travel_time_produces_a_leave_now_verdict(self, client):
        client.post("/api/v1/admin/ingest", headers=ADMIN)
        body = client.get(
            "/api/v1/crossings/siraspur/status?travel_seconds=600"
        ).json()
        assert body["advice"]["verdict"] in {"go", "tight", "wait"}
        assert body["advice"]["travel_seconds"] == 600

    def test_invalid_travel_time_is_rejected(self, client):
        response = client.get("/api/v1/crossings/siraspur/status?travel_seconds=99999")
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"

    def test_request_id_is_echoed_for_tracing(self, client):
        response = client.get("/health/live", headers={"X-Request-ID": "abc123"})
        assert response.headers["X-Request-ID"] == "abc123"


class TestReports:
    def test_a_user_report_is_accepted(self, client):
        response = client.post(
            "/api/v1/crossings/siraspur/reports",
            json={"state": "closed", "note": "long freight", "client_id": "test-client"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["accepted"] is True
        # Nothing predicted this closure, so it is the freight signal.
        assert body["outcome"] in {"unexplained", "corroborated"}
        assert body["next_report_at"]

    def test_an_immediate_second_tap_is_declined_not_double_counted(self, client):
        payload = {"state": "closed", "client_id": "same-browser"}
        client.post("/api/v1/crossings/siraspur/reports", json=payload)
        second = client.post("/api/v1/crossings/siraspur/reports", json=payload).json()
        assert second["accepted"] is False
        assert second["outcome"] == "duplicate"

    def test_an_invalid_state_is_rejected(self, client):
        assert client.post(
            "/api/v1/crossings/siraspur/reports", json={"state": "maybe"}
        ).status_code == 422


class TestAdmin:
    def test_admin_requires_the_key(self, client):
        assert client.get("/api/v1/admin/diagnostics").status_code == 401

    def test_diagnostics_returns_the_whole_picture(self, client):
        body = client.get("/api/v1/admin/diagnostics", headers=ADMIN).json()
        assert "budget" in body and "providers" in body
        assert body["crossings"][0]["segment"] == "BHD → KHKN"

    def test_a_crossing_can_be_added_without_a_deploy(self, client):
        payload = {
            "slug": "test-gate",
            "name": "Test Gate",
            "latitude": 28.0,
            "longitude": 77.0,
            "prev_station_code": "AAA",
            "next_station_code": "BBB",
            "distance_from_prev_km": 1.0,
            "distance_from_next_km": 2.0,
        }
        assert client.post("/api/v1/crossings", json=payload,
                           headers=ADMIN).status_code == 201
        assert client.get("/api/v1/crossings/test-gate").status_code == 200

    def test_duplicate_slug_is_rejected(self, client):
        payload = {
            "slug": "siraspur",
            "name": "Dupe",
            "latitude": 28.0,
            "longitude": 77.0,
            "prev_station_code": "AAA",
            "next_station_code": "BBB",
            "distance_from_prev_km": 1.0,
            "distance_from_next_km": 2.0,
        }
        assert client.post("/api/v1/crossings", json=payload,
                           headers=ADMIN).status_code == 422

    def test_accuracy_endpoint_is_available_from_day_one(self, client):
        body = client.get("/api/v1/crossings/siraspur/accuracy").json()
        assert body["crossing_slug"] == "siraspur"
        assert "summary" in body


class TestCachedResponseCorrectness:
    def test_countdowns_are_recomputed_on_a_cache_hit(self, client):
        """A cached payload keeps its absolute instants but must never serve a
        stale duration — that is the whole reason durations are derived."""
        client.post("/api/v1/admin/ingest", headers=ADMIN)
        first = client.get("/api/v1/crossings/siraspur/status").json()
        second = client.get("/api/v1/crossings/siraspur/status")

        assert second.headers["X-Cache"] == "hit"
        body = second.json()
        # Same underlying prediction...
        assert body["generated_at"] == first["generated_at"]
        if body["next_closure"]:
            assert body["next_closure"]["close_at"] == first["next_closure"]["close_at"]
            # ...but the countdown moved with the clock, never backwards in time.
            assert body["seconds_until_close"] <= first["seconds_until_close"]
        assert body["server_time"] >= first["server_time"]


class TestAdviceCopy:
    """Regression: integer division rendered a sub-minute wait as
    'about 0 min of waiting', which reads like a bug to someone holding keys."""

    def _advice(self, now, minutes_ahead, travel_seconds):
        from app.core.config import get_settings
        from app.db.session import session_scope
        from app.providers.timetable import TimetableProvider
        from app.services.learning.engine import LearningEngine
        from app.services.prediction.engine import PredictionEngine
        from app.services.status_service import StatusService
        from tests.factories import direct_sighting

        engine = PredictionEngine()
        svc = StatusService(
            engine=engine, learning=LearningEngine(), settings=get_settings(),
            fallback_provider=TimetableProvider(session_scope=session_scope),
        )
        from app.domain import CrossingRef

        ref = CrossingRef(
            id=1, slug="x", name="X", latitude=0, longitude=0,
            prev_station_code="A", next_station_code="B",
            distance_from_prev_km=1.0, distance_from_next_km=1.0,
        )
        prediction = engine.predict(
            crossing=ref, sightings=[direct_sighting(now=now, minutes_ahead=minutes_ahead)],
            now=now,
        )
        return svc._advice(list(prediction.windows), now, travel_seconds)

    def test_sub_minute_wait_reads_naturally(self, now):
        advice = self._advice(now, minutes_ahead=5, travel_seconds=340)
        if advice and advice.verdict == "wait":
            assert "0 min" not in advice.reason
            assert "under a minute" in advice.reason or "about 1 min" in advice.reason

    def test_no_advice_without_a_travel_time(self, now):
        assert self._advice(now, minutes_ahead=5, travel_seconds=None) is None


class TestFallbackHonesty:
    """The read path must never present timetable data as live."""

    def test_status_flags_fallback_windows_and_says_why(self, client):
        from datetime import datetime, timedelta, timezone

        from app.db.models import ClosureWindow as Row
        from app.db.session import session_scope

        # A window persisted by a degraded tick, fresh enough not to be stale.
        now = datetime.now(tz=timezone.utc)
        with session_scope() as s:
            from app.db.models import Crossing

            cid = s.query(Crossing).one().id
            s.add(
                Row(
                    crossing_id=cid,
                    close_at=now + timedelta(minutes=20),
                    open_at=now + timedelta(minutes=25),
                    source="predicted",
                    confidence=0.6,
                    causes=[],
                    is_superseded=False,
                    degraded=True,
                )
            )

        body = client.get("/api/v1/crossings/siraspur/status").json()
        assert body["data"]["degraded"] is True
        assert any("live train feed" in n for n in body["data"]["notes"]), body["data"]["notes"]
