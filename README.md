<div align="center">

# Phatak Live

**Should I leave home now, or will the gate close before I reach it?**

A production-grade web application that predicts when an Indian railway level
crossing (*phatak*) will close and reopen.

[Architecture](docs/ARCHITECTURE.md) · [Research](docs/RESEARCH.md) · [API](docs/API.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Developer guide](docs/DEVELOPER_GUIDE.md) ·
[Roadmap](docs/ROADMAP.md)

</div>

---

## What this is

Phatak Live is **not** a train tracker and **not** a timetable. Those already exist, and
neither answers the question people actually have when they pick up their keys.

The homepage answers exactly one question, in one screen:

```
              ● Gate right now
                  OPEN

           Expected to close in
                  04:12

  If I leave now →  Go now. The gate is expected
                    to be open when you arrive.
```

Underneath, it models the *crossing* — not the train:

- **Live status** — open, closing soon, or closed
- **Countdown** to the next closure and to reopening
- **The train responsible**, its direction, speed and delay
- **A confidence score that explains itself**
- **Today's closure history**
- **A direct verdict** for your travel time: go, tight, or wait
- **Pull down to refresh** — asks the server to go and look, within a metered budget

Target crossing: **Siraspur Railway Crossing**, North West Delhi, on the Northern Railway
Delhi–Panipat corridor between Badli (BHD) and Khera Kalan (KHKN). The architecture generalises to
any level crossing in India — adding one is a `POST /api/v1/crossings`, not a code change.

## Live

| | |
|---|---|
| **App** | https://phatak-live.vercel.app |
| **API** | https://phatak-api.onrender.com ([docs](https://phatak-api.onrender.com/docs)) |

Running free on Vercel (frontend) + Render (API) + Neon (Postgres). On a phone,
**Share → Add to Home Screen** installs it as a PWA.

## Quick start

```bash
git clone <this-repo> && cd phatak-live
cp .env.example .env          # optional: add RAILRADAR_API_KEY
docker compose up --build
```

- App → <http://localhost:3000>
- API docs → <http://localhost:8000/docs>

**Without an API key the stack still works.** A deterministic mock provider generates a plausible
Siraspur traffic pattern, so you can see, click and demo the whole product before you have
credentials. Get a free key (50 requests/day) at [railradar.in/developers](https://railradar.in/developers).

<details>
<summary>Running without Docker</summary>

```bash
# Backend — http://localhost:8000
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload

# Frontend — http://localhost:3000
cd frontend
npm install
API_BASE_URL=http://localhost:8000 npm run dev
```
</details>

## How it works

```mermaid
flowchart LR
    P["Providers<br/>RailRadar · REST · Timetable"] -->|TrainSighting| E["Prediction engine<br/>(pure function)"]
    E -->|ClosureWindow[]| DB[(Database)]
    DB --> API["FastAPI"] --> UI["Next.js PWA"]
    UI -->|"gate is shut"| OBS["Observations"]
    DB --> OBS --> L["Learning engine<br/>EWMA calibration"] --> E
```

Four ideas carry the whole design:

1. **The crossing lies between two known stations.** So a pass time can be interpolated from
   per-station timings alone — no GPS required. Two station-board API calls per poll cover
   *every* train on the segment, regardless of traffic. This is what makes the free tier viable
   and national scale affordable ([ADR 0003](docs/adr/0003-station-board-first-ingestion.md)).

2. **The prediction engine is a pure function** of `(now, crossing, sightings, calibration)`.
   No I/O, no ambient clock. Every scenario is a table-driven test, past predictions replay
   exactly, and horizontal scaling is trivial ([ADR 0002](docs/adr/0002-pure-prediction-engine.md)).

3. **The gate model is physical, not a magic constant.** Closure lead time is
   `approach_distance ÷ speed`, so a 95 km/h Shatabdi and a 40 km/h goods train produce different,
   correct windows. Reopening accounts for train length. This is why it generalises.

4. **Every prediction is graded against what actually happened**, and per-crossing, per-train-class
   offsets are learned by EWMA. The system gets better at *this* gate over time — and it can show
   you its own error statistics at `/api/v1/crossings/{slug}/accuracy`.

5. **A pull is a question, not a command.** Pull-to-refresh triggers a live
   provider fetch *only* if newer data would actually exist and the metered
   daily allowance can afford it — otherwise it says so rather than faking a
   spinner. Concurrent pulls collapse into one upstream call.

6. **Even the map fixes itself.** A wrong chainage leaves a directional fingerprint (UP trains
   biased one way, DOWN the other). The geometry calibrator detects it and moves the crossing
   along its segment — bounded, rate-limited, and fully audited — so seeded estimates converge
   on surveyed truth without a deploy.

## What it will not pretend to know

Indian Railways publishes no freight running data — anywhere, to anyone. At Siraspur, goods trains
are a real share of closures. Rather than quietly being wrong, Phatak Live:

- reduces confidence during historically freight-heavy windows,
- records unexplained closures and exposes a `freight_risk` band,
- lets anyone at the gate tap **"it's shut"**, which becomes training data,
- and never invents a countdown for a train it cannot see.

The confidence number is capped at 0.97. We are predicting the behaviour of a human gatekeeper
reacting to a train we are inferring. Certainty would be a lie.

## Repository layout

```
backend/            FastAPI service
  app/core/         config, clock, cache, retry, circuit breaker, budget, metrics
  app/domain.py     provider-neutral domain objects
  app/providers/    RailRadar · generic REST · timetable · mock · failover chain
  app/services/     prediction engine · learning engine · ingest · status
  app/api/          v1 routers, health, admin diagnostics
  alembic/          versioned migrations
  tests/            179 tests: unit, integration, failure modes, load profile
frontend/           Next.js 15 PWA (App Router, TypeScript, Tailwind)
docs/               research, architecture, ADRs, API, deployment, ops
.github/workflows/  CI, CodeQL
```

## Status

| Area | State |
|---|---|
| Backend, providers, prediction, learning | ✅ Complete |
| Frontend PWA | ✅ Complete |
| Tests | ✅ 179 passing |
| Docker / CI / Render blueprint | ✅ Complete |
| Live provider integration | ⚠️ Needs your API key |
| Crossing geometry | ⚠️ Approximate seed — **self-correcting** from live data ([how](docs/TROUBLESHOOTING.md#the-predictions-are-consistently-early-or-late)) |
| Web Push notifications | 🔜 Schema shipped, delivery on the roadmap |

## Safety

This is a prediction, not a signal. **Never use this application to decide whether to cross a
railway line.** Obey the gate, the gatekeeper and the signals, always.

## Licence

MIT — see [LICENSE](LICENSE).
