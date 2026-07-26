"""Shared fixtures.

Every test gets an isolated file-backed SQLite database and a frozen clock, so
nothing is timing-dependent and nothing leaks between tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest

# The test suite must never touch a real network, and an ambient SOCKS/HTTP
# proxy in the environment would defeat request mocking.
for _proxy_var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                   "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_proxy_var, None)
os.environ["NO_PROXY"] = "*"

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("LOG_FORMAT", "console")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from app.core.clock import IST, FrozenClock, to_utc  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.db import session as session_module  # noqa: E402
from app.db.models import Crossing  # noqa: E402
from app.db.seed import seed_siraspur  # noqa: E402
from app.domain import CrossingRef  # noqa: E402
from app.services.crossing_service import to_ref  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    get_settings.cache_clear()
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path/'test.db'}"
    return get_settings()


@pytest.fixture
def db(settings: Settings) -> Iterator[None]:
    session_module.reset_state()
    session_module.create_all()
    yield
    session_module.reset_state()


@pytest.fixture
def session(db) -> Iterator:
    with session_module.session_scope() as s:
        yield s


@pytest.fixture
def now() -> datetime:
    """A fixed, unremarkable Tuesday morning in IST."""
    return to_utc(datetime(2026, 7, 21, 8, 0, 0, tzinfo=IST))


@pytest.fixture
def clock(now: datetime) -> FrozenClock:
    return FrozenClock(now)


@pytest.fixture
def crossing_row(session) -> Crossing:
    crossing = seed_siraspur(session)
    session.flush()
    return crossing


@pytest.fixture
def crossing(crossing_row: Crossing) -> CrossingRef:
    return to_ref(crossing_row)


@pytest.fixture
def ref() -> CrossingRef:
    """A pure in-memory crossing for engine tests (no database at all)."""
    return CrossingRef(
        id=1,
        slug="siraspur",
        name="Siraspur Railway Crossing",
        latitude=28.7565,
        longitude=77.1273,
        prev_station_code="BHD",
        next_station_code="KHKN",
        distance_from_prev_km=1.2,
        distance_from_next_km=2.1,
        approach_distance_km=2.5,
        min_close_lead_seconds=120,
        max_close_lead_seconds=600,
        reopen_lag_seconds=75,
        min_gate_cycle_seconds=210,
    )


@pytest.fixture
def minutes():
    def _minutes(n: float) -> timedelta:
        return timedelta(minutes=n)

    return _minutes
