"""Load profile.

Models the real access pattern: almost every request is the same status poll
from a phone, which is exactly what the 15 s response cache is designed for.

    locust -f tests/locustfile.py --host http://localhost:8000
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task


class Commuter(HttpUser):
    """Someone about to leave the house, refreshing the page."""

    wait_time = between(5, 20)

    @task(20)
    def check_status(self) -> None:
        self.client.get(
            "/api/v1/crossings/siraspur/status",
            name="/crossings/{slug}/status",
        )

    @task(5)
    def check_status_with_travel_time(self) -> None:
        travel = random.choice([180, 300, 420, 600])
        self.client.get(
            f"/api/v1/crossings/siraspur/status?travel_seconds={travel}",
            name="/crossings/{slug}/status?travel_seconds",
        )

    @task(1)
    def list_crossings(self) -> None:
        self.client.get("/api/v1/crossings")

    @task(1)
    def health(self) -> None:
        self.client.get("/health/live")
