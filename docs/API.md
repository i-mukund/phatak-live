# API Reference

Base URL: `/api/v1` · Interactive docs: `/docs` (Swagger) and `/redoc` · Schema: `/openapi.json`

## Conventions

**Every instant is an absolute ISO-8601 timestamp in IST**, e.g. `2026-07-26T18:42:00+05:30`.
The API never returns a duration like "closes in 240 seconds", because a response cached for
15 seconds would then be wrong for 15 seconds. **Compute countdowns on the client** by
subtracting from the device clock.

Errors share one envelope:

```json
{
  "code": "not_found",
  "message": "No crossing with slug 'nowhere'",
  "detail": null,
  "trace_id": "9f2c1ab84d2e5107"
}
```

| Code | HTTP | Meaning |
|---|---|---|
| `not_found` | 404 | Unknown crossing |
| `validation_error` | 422 | Bad request body or query parameter |
| `unauthorized` | 401 | Missing or wrong `X-Admin-Key` |
| `provider_error` | 502 | Upstream data source failed (never surfaced on `/status`) |
| `internal_error` | 500 | Bug on our side — quote the `trace_id` |

Send `X-Request-ID` and it is echoed back and threaded through every log line for that request.

---

## `GET /crossings`

Active crossings.

```json
[
  {
    "slug": "siraspur",
    "name": "Siraspur Railway Crossing",
    "city": "Delhi",
    "state": "Delhi",
    "latitude": 28.7565,
    "longitude": 77.1273,
    "line_name": "Northern Railway — Delhi Jn ↔ Panipat / Ambala",
    "up_towards": "Khera Kalan",
    "down_towards": "Badli"
  }
]
```

`up_towards` / `down_towards` exist so clients can label directions without hard-coding
anything about a specific crossing.

## `GET /crossings/{slug}`

Adds the segment geometry and gate-behaviour parameters: bracketing stations, chainages,
`approach_distance_km`, `reopen_lag_seconds`, `min_gate_cycle_seconds`, `track_count`.

## `GET /crossings/{slug}/status` ← the one that matters

The only endpoint the app polls. Poll every 15 s; the server caches for 15 s and sets
`Cache-Control: max-age=10, stale-while-revalidate=30`.

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `travel_seconds` | int, 0–7200 | How long *you* need to reach the gate. Adds the `advice` block. |

**Response (abridged)**

```json
{
  "crossing": { "slug": "siraspur", "name": "Siraspur Railway Crossing", "...": "..." },
  "generated_at": "2026-07-26T18:39:12+05:30",
  "server_time":  "2026-07-26T18:39:20+05:30",

  "state": "closing_soon",
  "seconds_until_close": 156.4,
  "seconds_until_open": null,

  "current_closure": null,
  "next_closure": {
    "close_at": "2026-07-26T18:41:56+05:30",
    "open_at":  "2026-07-26T18:46:31+05:30",
    "duration_seconds": 275.0,
    "confidence": 0.81,
    "causes": [
      {
        "train_number": "12011",
        "train_name": "Kalka Shatabdi Express",
        "train_class": "shatabdi",
        "direction": "up",
        "pass_at": "2026-07-26T18:43:35+05:30",
        "speed_kmph": 95.0,
        "delay_minutes": 4,
        "provider": "railradar",
        "estimator": "blend"
      }
    ]
  },
  "upcoming": [ "...more windows..." ],

  "approaching_train": { "train_number": "12011", "...": "..." },

  "confidence": {
    "score": 0.81,
    "label": "high",
    "factors": {},
    "notes": ["Position is interpolated, not GPS-observed."]
  },

  "today": {
    "date": "2026-07-26",
    "closure_count": 14,
    "total_closed_seconds": 3780.0,
    "longest_closure_seconds": 512.0,
    "closures": [ "...most recent first..." ]
  },

  "data": {
    "providers_used": ["railradar"],
    "degraded": false,
    "stale": false,
    "freight_risk": 0.12,
    "last_updated_at": "2026-07-26T18:39:12+05:30",
    "notes": []
  },

  "advice": {
    "travel_seconds": 300,
    "arrival_at": "2026-07-26T18:44:20+05:30",
    "can_cross": false,
    "verdict": "wait",
    "reason": "The gate is expected to be shut when you arrive; about 2 min of waiting. Leaving in 7 min avoids it."
  }
}
```

**Field notes worth reading**

- `state` — `open` · `closing_soon` (≤5 min away) · `closed`.
- `causes` — the trains that produced this window. Two trains 90 s apart yield **one** window
  with two causes, because a gate that reopens for 90 s does not really reopen.
- `estimator` — how the pass time was derived: `schedule`, `kinematic`, `blend` or `direct`
  (timetable only). Useful when debugging a bad prediction.
- `confidence.score` — 0–0.97. See [ARCHITECTURE §5](ARCHITECTURE.md) for the factors.
- `data.degraded` — true when no live provider answered and the offline timetable is being used.
  The response is still valid, just less certain.
- `data.stale` — the last successful ingest is older than `MAX_SIGHTING_AGE_SECONDS`.
- `data.freight_risk` — 0–1, share of recent closures at this hour that no known train explained.

**This endpoint never fails because an upstream API failed.** It reads materialised windows from
our own database; if there are none, it computes them from the local timetable. Provider I/O
happens only in the background scheduler.

## `POST /crossings/{slug}/refresh`

Pull-to-refresh. Triggers a live provider fetch **if it would help and the
budget can afford it**, then returns the resulting status in the same response.

```json
{
  "refreshed": true,
  "outcome": "refreshed",
  "reason": "Updated with the latest train positions.",
  "data_age_seconds": 0.0,
  "next_refresh_at": "2026-07-26T13:43:57+05:30",
  "status": { "...full CrossingStatus..." }
}
```

`outcome` is one of:

| Value | Meaning |
|---|---|
| `refreshed` | A live fetch happened; `status` is new |
| `already_fresh` | Newest data is younger than `MANUAL_REFRESH_MIN_AGE_SECONDS`; nothing to gain |
| `budget_protected` | Daily upstream allowance is nearly spent; scheduled ingestion has first claim |
| `provider_failed` | Upstream unreachable; last known prediction returned |

Unauthenticated by design — it *is* the pull gesture — and therefore guarded
three ways: freshness threshold, budget floor, and single-flight collapsing so
a herd of simultaneous pulls costs exactly one upstream fetch. **Clients must
not present a refusal as a successful refresh**; surface `reason` instead.

## `POST /crossings/{slug}/reports`

Crowd report from someone standing at the gate — the only signal that sees freight.

```http
POST /api/v1/crossings/siraspur/reports
Content-Type: application/json

{ "state": "closed", "note": "long goods train", "client_id": "b3f1…" }
```

```json
{
  "accepted": true,
  "outcome": "unexplained",
  "message": "Thanks — we didn't predict this one. Unexplained closures are usually freight…",
  "reported_at": "2026-07-26T18:26:38+05:30",
  "next_report_at": "2026-07-26T18:36:38+05:30",
  "corroborations": 2,
  "id": 42
}
```

| `outcome` | Meaning |
|---|---|
| `corroborated` | Falls inside a closure we predicted — the model was right |
| `unexplained` | Nothing we know about closed this gate; feeds `freight_risk` |
| `recorded` | An "open" report; logged, carries no freight signal |
| `duplicate` | Same client, same crossing, inside the cooldown — not counted again |
| `rate_limited` | Per-IP hourly ceiling hit |

**Clients must honour `accepted`.** Show `message`; do not render a refusal as a
successful report. Use `next_report_at` to re-enable the control — the state
must not be terminal, since one person legitimately crosses the same gate twice
a day.

`client_id` is a random id the browser generates and keeps in `localStorage`.
The server stores only a salted SHA-256 of it, alongside a hash of the client
IP used solely for rate limiting. It identifies a browser, not a person; there
is no account or cookie.

### Why abuse is uninteresting here

Rate limits buy time; the real defence is limiting what the data may influence.
Crowd reports can only **corroborate a predicted closure** or **flag an
unexplained one**. Timing offsets are driven exclusively by provider
`actualArrival` times, which cannot be forged through this endpoint. The worst
outcome of a successful campaign is an inflated freight-risk percentage — it
cannot move a single countdown. There is a test asserting exactly that
(`test_crowd_reports_cannot_move_a_calibration_offset`).

## `GET /crossings/{slug}/accuracy?days=14`

Are we actually any good? Returns bias, MAE, p50/p90 absolute error, the share of predictions
within two minutes, and the current calibration profile per train class.

```json
{
  "crossing_slug": "siraspur",
  "summary": {
    "samples": 214, "days": 14,
    "bias_seconds": -18.4, "mae_seconds": 96.2,
    "p50_abs_seconds": 71.0, "p90_abs_seconds": 208.0,
    "within_2min_pct": 78.5
  },
  "calibration": [
    { "train_class": "shatabdi", "pass_offset_seconds": -22.4, "sample_count": 61, "...": "..." }
  ]
}
```

## `POST /crossings` 🔒

Add a crossing. Requires `X-Admin-Key`. Scaling to a new crossing is configuration, not code.

```json
{
  "slug": "example-gate",
  "name": "Example Gate",
  "latitude": 28.75, "longitude": 77.12,
  "prev_station_code": "BHD", "next_station_code": "KHKN",
  "distance_from_prev_km": 1.8, "distance_from_next_km": 3.0,
  "approach_distance_km": 2.5, "reopen_lag_seconds": 75,
  "min_gate_cycle_seconds": 210, "track_count": 2
}
```

## Admin 🔒

| Endpoint | Purpose |
|---|---|
| `GET /admin/diagnostics` | Provider health, circuit-breaker states, API budget, last tick, calibration — everything, in one call |
| `POST /admin/ingest` | Force an ingest tick now |
| `POST /admin/grade` | Force prediction grading now |
| `POST /admin/cache/clear` | Flush the response cache |

Admin routes **fail closed** in production when `ADMIN_API_KEY` is unset, and are open in
development so nobody wastes an afternoon on a 401 locally.

## Health & metrics

| Endpoint | Purpose |
|---|---|
| `GET /health/live` | Process is up. Never fails because a provider is down. |
| `GET /health/ready` | Database reachable **and** at least one provider healthy. `503` otherwise. |
| `GET /metrics` | Prometheus exposition |

Metrics: `phatak_provider_requests_total{provider,outcome}`, `phatak_provider_latency_seconds`,
`phatak_prediction_error_seconds{crossing,event}`, `phatak_circuit_breaker_open{provider}`,
`phatak_api_budget_remaining`, `phatak_ingest_ticks_total{outcome}`, `phatak_sightings_total{provider}`.

## Rate limits

The API itself is unmetered — it is read-mostly and cached. The constrained resource is the
*upstream* provider quota, which is governed server-side by `API_DAILY_REQUEST_BUDGET`.
Polling `/status` more often than every 10 s gains you nothing: it is served from cache.
