"""Prometheus metrics. Import-safe and idempotent across test reloads."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

PROVIDER_REQUESTS = Counter(
    "phatak_provider_requests_total",
    "Upstream provider requests by outcome.",
    ["provider", "outcome"],
    registry=REGISTRY,
)
PROVIDER_LATENCY = Histogram(
    "phatak_provider_latency_seconds",
    "Upstream provider latency.",
    ["provider"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
    registry=REGISTRY,
)
PREDICTION_ERROR = Histogram(
    "phatak_prediction_error_seconds",
    "Signed error between predicted and observed gate events.",
    ["crossing", "event"],
    buckets=(-600, -300, -120, -60, -30, 0, 30, 60, 120, 300, 600),
    registry=REGISTRY,
)
CIRCUIT_STATE = Gauge(
    "phatak_circuit_breaker_open",
    "1 when a provider circuit breaker is open.",
    ["provider"],
    registry=REGISTRY,
)
BUDGET_REMAINING = Gauge(
    "phatak_api_budget_remaining",
    "Remaining upstream request budget for the current IST day.",
    registry=REGISTRY,
)
INGEST_TICKS = Counter(
    "phatak_ingest_ticks_total",
    "Scheduler ingest ticks by outcome.",
    ["outcome"],
    registry=REGISTRY,
)
SIGHTINGS_SEEN = Counter(
    "phatak_sightings_total",
    "Normalised train sightings produced, by provider.",
    ["provider"],
    registry=REGISTRY,
)
