# Stage 1 — Live Train Data Source Research

**Status:** Accepted · **Date:** 2026-07-25 · **Owner:** Phatak Live Engineering

---

## 1. The question we are actually answering

Phatak Live does **not** track trains. It predicts the behaviour of a *level crossing* (a
"phatak"). The only reason we touch train data at all is to answer one question:

> At what wall-clock instant will a train physically occupy the crossing at
> `(lat, lng)`, and therefore when will the gate be down?

That reframing matters, because it changes what "good data" means:

| Train-tracking product needs | Phatak Live needs |
| --- | --- |
| Position of *one* train the user chose | Position of *every* train on *one* track segment |
| Accuracy over the whole journey | Accuracy over a ±3 km window around one point |
| Nice map | Accurate `t_pass` and its uncertainty |
| Freight is irrelevant | **Freight is critical** (it closes gates and is invisible to passenger APIs) |

Consequence: an API that is excellent for "where is my train" can still be a poor fit here,
and the *station board* endpoints turn out to be more valuable per API call than the
*live train status* endpoints. See §5.

## 2. Target crossing

**Siraspur Railway Crossing** — Siraspur Road, Kankar Khera village, North West Delhi 110042.

- Sits on the Northern Railway **Delhi Jn – Panipat / Ambala** corridor.
- Bracketing stations: **Badli (BHD)** and **Khera Kalan (KHKN)**; the segment is **3.3 km** by
  railway chainage (verified live against RailRadar, 2026-07-26), with the crossing nearer Badli.
- High traffic: EMU/MEMU locals, Delhi–Ambala/Kalka expresses, and heavy freight paths.

The bracketing-station geometry is the single most important modelling fact: the crossing lies
*inside a single inter-station segment*, so any provider that reports per-station actual times
lets us interpolate a pass time without needing GPS.

> ⚠️ The exact latitude/longitude and the 1.8 / 3.0 km chainages in `seed.py` are derived from
> public map data and **must be field-verified** before the numbers are treated as ground truth.
> They are configuration, not code — see `backend/app/db/seed.py`.

## 3. Sources evaluated

| # | Source | Type | Auth | Coverage | Verdict |
|---|---|---|---|---|---|
| 1 | **RailRadar** (`api.railradar.in/v1`) | Commercial REST, documented, versioned | Bearer API key | Live position, delay, per-stop actuals, station live board, GeoJSON route | ✅ **Primary** |
| 2 | **NTES / CRIS** (`enquiry.indianrail.gov.in`) | Official public site, **no public API** | none (captcha/obfuscated) | Authoritative | ⚠️ Reference only — not integrated |
| 3 | **IRCTC / Indian Railways official API** | Does not exist publicly for live running | — | — | ❌ Unavailable |
| 4 | **indianrailapi.com** | Commercial REST | key | Similar surface, thinner live data | 🟡 Secondary (adapter shipped) |
| 5 | **erail.in / RailYatri / trains.im scrapers** | HTML scraping | none | Broad | ❌ Rejected — ToS + brittleness |
| 6 | **"Where Is My Train" (Google)** | Crowd-sourced app, private API | — | Excellent, incl. GPS | ❌ No public API, reverse engineering rejected |
| 7 | **OpenRailwayMap / OSM** | Static geodata (ODbL) | none | Track geometry, level-crossing nodes | ✅ **Adopted for geometry**, not for live |
| 8 | **Community GitHub wrappers** (`indian-railways-api` topic) | Unofficial wrappers over 2/5 | varies | Varies | ❌ Inherit upstream fragility |
| 9 | **Local timetable (our own DB)** | Offline schedule seeded per crossing | none | 100 % uptime, no live delay | ✅ **Always-on fallback** |
| 10 | **Crowd reports from our own users** | First-party | our auth | Freight + ground truth | ✅ **Roadmap + already modelled** |

### 3.1 Why not NTES directly

NTES is the authoritative CRIS system, and it is tempting because it is free and official.
We rejected direct integration for three reasons:

1. **There is no API.** There is an HTML/JS site with obfuscated, session-bound endpoints.
   Consuming it means scraping.
2. **Terms of use.** The portal is published for personal enquiry use. Automated harvesting for
   a third-party product is not a use the site grants, and we are not willing to build a
   production dependency on a legally grey scrape.
3. **Operational fragility.** Scrapers of this class break on every markup change and are the
   #1 source of 3 a.m. pages.

We therefore treat NTES as the *human* source of truth for spot-checking our accuracy, and we
document how to do that in `docs/TROUBLESHOOTING.md`. If CRIS ever publishes an API, adding it
is a ~150-line adapter (§6) — that is the whole point of the provider abstraction.

### 3.2 Why RailRadar as primary

- Documented, versioned REST API with a **stable response envelope** (`success`/`data`/`meta`).
- Provides exactly the two shapes we need:
  - `GET /v1/stations/{code}/live?hours=2&includeIntermediate=true` → every train due at a
    station, **including non-halting pass-through trains**, with `delayMinutes` and
    `expectedDepartureTime`.
  - `GET /v1/trains/{number}/live` → per-stop `actualArrival`/`actualDeparture`,
    `currentLocation.segmentProgress`, `speedKmh`, `isActualPosition`.
- `isActualPosition` is unusually honest: it tells us whether a position is *observed* or
  *interpolated*. We feed that straight into our confidence score.
- Explicit, documented error codes including `429` and `503`, which makes correct backoff easy.

**The catch:** the free tier is **50 requests/day, 10/min**. A naive implementation
(poll every train's live status every 30 s) would burn the daily quota in under a minute.
This constraint drove the core architectural decision below.

### 3.3 Freight: the honest limitation

No public Indian Railways data source exposes freight (goods) train running. At Siraspur,
freight is a material share of gate closures. We handle this in three ways, all of which are
implemented or modelled rather than hand-waved:

1. **Statistical freight prior** — the learning engine records closures that no known passenger
   train explains, and builds a per-crossing, per-time-of-day *unexplained closure rate*. This
   is surfaced as a `freight_risk` band, never as a fake countdown.
2. **Confidence honesty** — during high-freight windows the confidence score is explicitly
   reduced. We would rather say "70 % confident" than invent a train.
3. **Crowd reports** — `GateReport` is a first-class table from day one; a single tap from a
   user standing at the gate becomes an observation the learning engine consumes.

## 4. Decision

> **Primary:** RailRadar. **Secondary:** generic REST adapter (indianrailapi-shaped).
> **Terminal fallback:** local seeded timetable provider, which cannot fail.
> **Geometry:** OpenRailwayMap/OSM-derived, stored locally.
> **Ground truth:** first-party crowd reports + provider-reported actuals.

No business logic may import a provider module. All prediction code consumes the neutral
`TrainSighting` domain object defined in `app/providers/base.py`.

## 5. The decision the rate limit forced: **station-board-first ingestion**

The obvious design is "for each train near the crossing, call live status." That is 1 call per
train per poll — 20 trains × 96 polls/day = 1 920 calls/day. Impossible on the free tier and
wasteful on a paid one.

Our design instead exploits the fact that **the crossing lies between exactly two stations**:

```
BHD (Badli) ──── 1.2 km ────► ✕ Siraspur ──── 2.1 km ────► KHKN (Khera Kalan)
```

A single `station live board` call at BHD and one at KHKN returns *every* train due at either
station in the next N hours, with live delay. From those two boards alone we can:

- enumerate candidate trains and their direction (which board sees them first),
- compute an expected pass time by interpolating between the two stations' expected times,
- do it in **2 API calls per poll cycle**, independent of traffic volume.

We then spend a small, configurable budget of `live train status` calls only on the **1–3
trains nearest the crossing**, where the extra precision (`segmentProgress`, `speedKmh`,
`isActualPosition`) actually changes the answer the user sees.

Result: **~2–5 calls per poll**, ~90 s poll interval ⇒ well within free-tier limits, with a
token-bucket budget guard (`app/core/budget.py`) that degrades to board-only mode rather than
getting 429'd. This is the difference between a demo and a product.

## 6. Replaceability contract

Adding a provider is a closed, mechanical task:

1. Implement `TrainDataProvider` (3 methods) in `app/providers/`.
2. Register it in `app/providers/registry.py` with a `trust` weight in `[0, 1]`.
3. Add its key to `Settings`.

Nothing else in the codebase changes. `FailoverChain` handles ordering, per-provider circuit
breakers, timeouts, and result merging (dedupe by train number, higher trust wins). Provider
trust flows automatically into the confidence score, so a weaker provider makes the UI *less
confident* rather than *equally confident and wrong*.

## 7. Risks accepted

| Risk | Mitigation |
| --- | --- |
| RailRadar changes schema / shuts down | Adapter isolation + contract tests over recorded fixtures + terminal timetable fallback |
| Free-tier quota exhaustion | Token-bucket budget, board-only degradation, response caching, `429` backoff |
| Freight invisibility | Statistical prior + crowd reports + honest confidence |
| Crossing geometry wrong | Geometry is seed data, correctable without deploy; learning engine absorbs residual bias |
| Gate operator behaviour varies | Per-crossing EWMA calibration of close-lead and reopen-lag (Stage 6) |

## 8. References

- RailRadar API docs — https://railradar.in/docs (endpoints, envelope, rate limits, error codes)
- RailRadar live train status — https://railradar.in/docs/live-train-status
- RailRadar station live board — https://railradar.in/docs/station-live-board
- National Train Enquiry System — https://enquiry.indianrail.gov.in/ntes/
- IndianRailAPI collection — https://indianrailapi.com/api-collection
- OpenRailwayMap — https://www.openrailwaymap.org/
