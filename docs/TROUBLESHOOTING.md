# Troubleshooting

Start here: `GET /api/v1/admin/diagnostics` (needs `X-Admin-Key`) returns provider health,
circuit-breaker states, remaining API budget, the last ingest tick and every calibration profile
in one response. It was written for exactly this page.

---

## The app says "no live train feed" / `degraded: true`

**What it means:** no primary provider returned usable data, so predictions come from the offline
timetable. The app is working as designed — this is failure mode F3.

**Check, in order:**

1. Is a key configured? `RAILRADAR_API_KEY` unset ⇒ the mock provider runs and everything is
   labelled degraded. The startup log says so explicitly.
2. `diagnostics.providers[].circuit.state` — `open` means we stopped calling a failing provider.
   It half-opens automatically after `CIRCUIT_BREAKER_RESET_SECONDS` (default 120 s).
3. `diagnostics.budget.remaining` — at 0 we stop spending until IST midnight.
4. Backend logs: `provider railradar failed: ...` carries the upstream reason.

## `429 Too Many Requests` from the provider

You are polling faster than your plan allows. RailRadar's free tier is 50 requests/day; the
default 90 s interval wants ~1 920.

```bash
# Free tier, honest settings:
INGEST_INTERVAL_SECONDS=2700     # 45 minutes
API_LIVE_CALLS_PER_TICK=0        # station boards only
API_DAILY_REQUEST_BUDGET=50
```

Predictions become schedule-grade rather than live-grade, and the confidence score drops to match.
That is the correct trade — not a bug.

## The predictions are consistently early or late

Check the bias first:

```bash
curl -s localhost:8000/api/v1/crossings/siraspur/accuracy | python3 -m json.tool
```

- `bias_seconds` **near zero, `mae_seconds` large** → noisy input (delays, interpolated positions).
  Nothing to fix in configuration; more samples will help the confidence factors, not the bias.
- `bias_seconds` **consistently positive** (trains arrive later than we say) → most often the
  seeded chainage is wrong. The crossing is further from `prev_station` than we think.
- `bias_seconds` **consistently negative** → the opposite.

**This page is now automated.** The geometry calibrator (runs inside the calibration job every
15 minutes) watches for the directional fingerprint of a chainage error — UP trains biased one
way, DOWN trains the other, since a plain timing bias shifts both the *same* way. When it has at
least 12 graded samples per direction, a median bias over ±45 s in opposite signs, and
speed-consistent estimates from both directions, it moves the crossing along the segment
(≤0.35 km per step, ≥3 days between steps, never past a station) and decays the EWMA offsets
that had been absorbing the error. Every change is recorded with its evidence in
`GET /api/v1/admin/geometry/history`; force a pass with `POST /api/v1/admin/geometry/review`.

The EWMA offsets also absorb bias on their own once ~10 graded samples exist per class. Manual
correction remains the fastest fix if you already know the real numbers:

```sql
UPDATE crossings
   SET distance_from_prev_km = 2.1, distance_from_next_km = 2.7
 WHERE slug = 'siraspur';
```

Then `POST /admin/cache/clear` and `POST /admin/ingest`.

> The Siraspur chainages shipped in `seed.py` are **map estimates and have not been surveyed**.
> The calibrator will converge on the truth by itself given a few days of graded live data, but a
> real measurement still gets there faster and is worth contributing.

## The gate closes for longer than predicted

Usually one of three things:

1. **Freight.** No public source publishes goods trains. Check `data.freight_risk` and today's
   unexplained closures. This is a known, documented limitation, not a bug.
2. **Two trains merged into one window** — expected behaviour. Check `causes` on the window.
3. **Reopen lag is wrong for this gate.** Some crossings hold the gate for a following move.
   Raise `reopen_lag_seconds` on the crossing row, or let the learning engine converge.

## "Today so far" shows zero closures

Windows are recorded as *predictions of the future* and become history as they elapse. On a fresh
database it fills in over the day. If it stays empty after a few hours, the scheduler is not
running — check `diagnostics.last_ingest_tick` and `SCHEDULER_ENABLED`.

## The scheduler never ticks

- `SCHEDULER_ENABLED=false`? (It is `false` in the test environment by default.)
- Running uvicorn with `--workers > 1`? Then N schedulers are competing and multiplying your API
  spend — enable it on exactly one process (see DEPLOYMENT.md §4).
- On a sleeping free-tier host the process is suspended; nothing ticks until a request wakes it.

## Frontend shows "Can't reach the gate"

The server-side render could not reach the API.

1. Is `API_BASE_URL` set for the **frontend** process? Inside Compose it must be the service name
   (`http://backend:8000`), not `localhost`.
2. `curl "$API_BASE_URL/health/live"` from inside the frontend container.
3. Browser console 503s from `/api/status/...` mean the Next route handler could reach the app but
   not the backend — same cause.

The page still recovers on its own once the API returns; it retries with backoff.

## CORS errors in the browser

Set `CORS_ORIGINS` to the exact frontend origin including scheme
(`https://phatak.example`, not `phatak.example`). Note that the PWA normally talks to the
same-origin Next route handler, so a CORS error usually means something is calling the backend
directly.

## Timestamps look wrong

All API timestamps are IST (`+05:30`) by design. If the countdown is off by hours, the **device**
clock or timezone is wrong — countdowns are computed client-side from absolute instants.

## Database is locked (SQLite)

WAL mode and a 5 s busy timeout are enabled, which handles the normal scheduler-vs-API overlap.
Persistent locking means multiple processes are sharing one SQLite file — move to PostgreSQL.
It is a one-line `DATABASE_URL` change.

## Tests fail with connection errors

The suite must never touch the network. `conftest.py` strips proxy environment variables for this
reason. If you see real connection attempts, a test is missing a `respx` mock.

## Alembic: "target database is not up to date"

```bash
cd backend
DATABASE_URL=... alembic current
DATABASE_URL=... alembic upgrade head
```

In production the app runs migrations on boot; set `AUTO_MIGRATE=false` if your release process
runs them separately.

## Verifying against ground truth

The authoritative human check is NTES: <https://enquiry.indianrail.gov.in/mntes/> — look up the
train the app blames for a closure and compare its expected times at BHD and KHKN with our
`causes[].pass_at`. Slow, but it settles arguments.
