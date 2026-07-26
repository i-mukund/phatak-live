# Deployment Guide

Three supported paths: Docker Compose (any VPS), Render (one blueprint), and manual. All three
run the same images and the same configuration surface.

---

## 1. Configuration

Everything is environment variables; nothing reads `os.environ` outside `app/core/config.py`.

### Required in production

| Variable | Why |
|---|---|
| `ENVIRONMENT=production` | Enables Alembic migrations on boot and fails admin routes closed |
| `DATABASE_URL` | PostgreSQL. `postgres://` URLs from Render/Heroku/Fly are normalised automatically |
| `ADMIN_API_KEY` | Without it, admin endpoints return 401 in production |
| `CORS_ORIGINS` | Full origin of your frontend, e.g. `https://phatak.example` |

### Strongly recommended

| Variable | Default | Notes |
|---|---|---|
| `RAILRADAR_API_KEY` | — | Without it the app runs on the mock provider. Fine for a demo, not for users |
| `API_DAILY_REQUEST_BUDGET` | `100` | Set to your plan's real limit. The budget guard degrades to board-only mode before you get 429'd |
| `CACHE_BACKEND=redis` + `REDIS_URL` | `memory` | Required if you run more than one API instance |
| `LOG_FORMAT=json` | `json` | Structured logs with `trace_id` |

### Tuning worth understanding

| Variable | Default | What it changes |
|---|---|---|
| `INGEST_INTERVAL_SECONDS` | `90` | Poll cadence. Cost scales linearly; 90 s × 2 calls ≈ 1 920/day, so **lower this only if your plan allows it** |
| `API_LIVE_CALLS_PER_TICK` | `2` | Expensive per-train enrichment calls per tick |
| `PREDICTION_HORIZON_MINUTES` | `120` | How far ahead windows are computed |
| `MAX_SIGHTING_AGE_SECONDS` | `900` | Sightings older than this are discarded and the response is flagged stale |
| `BLEND_HORIZON_KM` | `12` | Distance at which the kinematic estimator starts to dominate the schedule estimator |
| `RETENTION_DAYS` | `30` | Snapshot/window retention |

> **Free-tier reality check.** The activated free tier allows 100 requests/day. Each tick spends
> 2 essential board calls plus up to `API_LIVE_CALLS_PER_TICK` optional ones, so
> `INGEST_INTERVAL_SECONDS=1800` (30 min) fits the quota exactly: ~48 board ticks/day with the
> other half of the budget available for near-gate enrichment. The budget guard will not let you
> exceed the quota either way — it degrades instead of failing.

### Secrets

Never commit `.env`. Use your platform's secret store:

- **Render** — dashboard env vars with `sync: false` in `render.yaml` (already configured)
- **Docker Compose** — a `.env` file outside version control, or Docker secrets
- **Kubernetes** — a `Secret`, mounted as env

The only genuinely sensitive values are `RAILRADAR_API_KEY`, `ADMIN_API_KEY` and `DATABASE_URL`.

---

## 2. Docker Compose (recommended for a single box)

```bash
cp .env.example .env
$EDITOR .env                      # set RAILRADAR_API_KEY, ADMIN_API_KEY, POSTGRES_PASSWORD
docker compose up --build -d
docker compose logs -f backend
```

Brings up PostgreSQL, Redis, the API (`:8000`) and the PWA (`:3000`). Both app images run as
non-root with health checks. Migrations run automatically on backend start.

Put a TLS terminator in front (Caddy is two lines):

```
phatak.example {
  reverse_proxy /api/* backend:8000
  reverse_proxy frontend:3000
}
```

The backend runs uvicorn with `--proxy-headers`, so client IPs and scheme survive the hop.

## 3. Free hosting stack (Render + Vercel + Neon)

Genuinely £0/month, no card, nothing that expires:

| Piece | Host | Why |
|---|---|---|
| FastAPI backend | **Render** free web service | Docker support; 750 instance-hours/month covers one always-on service (~730 h) |
| Next.js frontend | **Vercel** Hobby | Vercel's own framework; free tier never sleeps and is CDN-backed |
| PostgreSQL | **Neon** free tier | Permanent (not a trial), 0.5 GB, 100 CU-hours/month, scales to zero when idle |

> **Do not put both services on Render's free tier.** The 750-hour allowance is shared across
> all free services, so two always-on services need ~1 460 h and the app would go dark part-way
> through every month. This is the single most common way a "free" deploy of this shape fails.

### Order of operations

1. **Neon** — create a project, copy the connection string
   (`postgresql://…?sslmode=require`). Compute suspends after 5 minutes idle; our 30-minute
   ingest tick wakes it, costing roughly 30 of the 100 monthly CU-hours.
2. **Render** — New → Blueprint → pick the repo. `render.yaml` defines the API. Set
   `DATABASE_URL` (from Neon) and `RAILRADAR_API_KEY` by hand; `ADMIN_API_KEY` is generated.
   Note the issued host, e.g. `https://phatak-api.onrender.com`.
3. **Vercel** — import the repo, set **Root Directory = `frontend`**, add
   `API_BASE_URL` = the Render host from step 2. Deploy.
4. **Close the loop** — set `CORS_ORIGINS` on Render to the Vercel origin
   (e.g. `https://phatak-live.vercel.app`) and let it redeploy.
5. **Keep the API awake** — a free [UptimeRobot](https://uptimerobot.com) monitor on
   `https://phatak-api.onrender.com/health/live` every 10 minutes. Render free services sleep
   after 15 minutes idle, which stops the scheduler; the pinger prevents that and stays inside
   the 750-hour budget.

### Free-tier characteristics worth knowing

- Neon storage is 0.5 GB. With `RETENTION_DAYS=30` a single crossing uses a few MB.
- If the API does sleep anyway, the first request afterwards is served from the timetable
  fallback and flagged `degraded` — correct behaviour, just less precise.
- Vercel Hobby is for non-commercial use. A free community utility qualifies; a monetised
  product would not.

## 4. Manual / systemd

```bash
cd backend
pip install -e ".[postgres]"
ENVIRONMENT=production DATABASE_URL=... alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers
```

> ⚠️ **With `--workers > 1`, set `SCHEDULER_ENABLED=false` on all but one process**, or every
> worker will poll the provider and multiply your API spend. The clean arrangement is one
> scheduler-enabled worker (or a separate scheduler deployment) plus N stateless API workers —
> the API never performs provider I/O, so this splits cleanly.

## 5. Scaling checklist

| When | Do this |
|---|---|
| >1 API instance | `CACHE_BACKEND=redis`; disable the scheduler on all but one |
| >10 crossings | Group by track segment — one station board serves every crossing on it (already how `IngestService` works) |
| >100 crossings | Separate scheduler deployment; shard ingest by railway zone |
| Heavy read load | Postgres read replica; the read path is a single indexed query plus cache |

## 6. Monitoring

Scrape `/metrics`. The four alerts that actually matter:

```yaml
- alert: PhatakIngestStalled
  expr: time() - max(phatak_ingest_ticks_total) == 0   # use a recording rule on last-tick
  for: 15m

- alert: PhatakAllProvidersDown
  expr: min(phatak_circuit_breaker_open) == 1
  for: 10m

- alert: PhatakBudgetNearlyGone
  expr: phatak_api_budget_remaining < 5

- alert: PhatakPredictionsDrifting
  expr: histogram_quantile(0.9, rate(phatak_prediction_error_seconds_bucket[6h])) > 300
  for: 1h
```

The last one is the interesting alert: it fires when the *product* is getting worse, not when a
process is unhealthy. That usually means the seeded geometry is wrong or gate operation changed.

For a human check, `GET /api/v1/admin/diagnostics` returns provider health, breaker states,
budget, last tick and calibration in a single call.

## 7. Backups

Only `crossings`, `timetable_entries`, `observations` and `calibration_profiles` are precious —
they are the learned behaviour. Windows and snapshots regenerate.

```bash
pg_dump -Fc "$DATABASE_URL" > phatak-$(date +%F).dump
```

## 8. Rollback

Images are immutable; roll back by redeploying the previous tag. If a migration is involved:

```bash
alembic downgrade -1
```

Every migration ships with a real `downgrade()`.
