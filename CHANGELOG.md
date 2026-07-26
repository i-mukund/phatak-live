# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-07-26

### Added

- **Autonomous geometry calibration.** The calibration job now detects the directional
  fingerprint of a wrong chainage (opposite-signed UP/DOWN pass bias, speed-consistent across
  both directions) and corrects the crossing's surveyed distances in place — median-based,
  bounded to 0.35 km per step, rate-limited to one adjustment per 3 days, never past a station,
  with every change and its evidence audited in a new `geometry_adjustments` table.
  Admin surface: `POST /admin/geometry/review`, `GET /admin/geometry/history`.
- `PredictionRecord` now stores direction and speed (Alembic migration `c51f20geocal`).
- 13 new tests, over half of which assert the calibrator *refuses* to act on the wrong
  signature (same-signed bias, outliers, thin data, cooldown).

## [1.0.0] — 2026-07-26

First production release.

### Added

- **Provider layer** — `TrainDataProvider` protocol with RailRadar (primary), a configurable
  generic REST adapter, an offline timetable provider that cannot fail, and a deterministic mock.
  Failover chain with per-provider circuit breakers, timeouts, retries with jittered backoff,
  trust-weighted deduplication and a daily upstream request budget.
- **Prediction engine** — pure function over `(now, crossing, sightings, calibration)`. Blends a
  schedule-interpolation estimator with a kinematic one, models gate lead/clear times physically
  from approach distance, speed and train length, merges closures the gate cannot realistically
  cycle between, and produces an explainable confidence score.
- **Learning engine** — records every prediction, derives ground truth automatically from provider
  actual times at the bracketing stations, accepts crowd reports, grades elapsed predictions and
  maintains EWMA calibration per crossing and train class. Public accuracy endpoint.
- **API** — FastAPI with OpenAPI, structured JSON logs with request tracing, typed errors,
  liveness/readiness split, Prometheus metrics and an admin diagnostics endpoint.
- **Frontend** — Next.js 15 PWA: server-rendered first paint, visibility-aware polling with
  exponential backoff, client-side countdowns from absolute timestamps, a "should I leave now?"
  verdict, crowd reporting and an offline-tolerant service worker.
- **Operations** — multi-stage Docker images running as non-root, Compose stacks for production
  and development, GitHub Actions CI with a smoke test, CodeQL, a Render blueprint and Alembic
  migrations (applied automatically in production).
- **Documentation** — data-source research, architecture with failure-mode table, three ADRs,
  API reference, deployment, developer, troubleshooting and roadmap guides.
- **Tests** — 146 covering core primitives, provider parsing against recorded payloads, every
  documented failure mode, prediction geometry and gate physics, the learning feedback loop, and
  the HTTP API end to end. Plus a Locust load profile.

### Known limitations

- Crossing chainages for Siraspur are derived from public map data and are **not field-verified**.
- No public data source publishes freight movements; unexplained closures are surfaced as a risk
  band rather than predicted.
- Web Push notifications are modelled and stubbed but not delivered in this release.
