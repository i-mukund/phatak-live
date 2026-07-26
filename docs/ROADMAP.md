# Roadmap

Ordered by how much each item improves the answer someone gets when they open the app.

## Shipped (v1.0)

- Provider abstraction with failover, circuit breakers and a request budget
- Station-board-first ingestion (2 API calls per tick, independent of traffic)
- Pure prediction engine: blended schedule + kinematic estimators, physical gate model,
  window merging, explainable confidence
- Learning engine: automatic grading from provider actuals, EWMA calibration per crossing and
  train class, public accuracy endpoint
- Mobile-first PWA: SSR first paint, live countdowns, "should I leave now?" verdict, crowd reports
- Docker, Compose, CI + CodeQL, Render blueprint, Alembic migrations
- 146 tests (91 % coverage) including one per documented failure mode

## Next — accuracy (the only thing that really matters)

1. **Field-verified geometry for Siraspur.** Everything downstream inherits this error. One
   afternoon with a GPS and the chainages stop being estimates.
2. **Per-time-of-day calibration.** Gate behaviour at 08:00 (peak, gate held for consecutive
   moves) differs from 14:00. The schema supports it; the key needs one more dimension.
3. **Consecutive-move detection.** When two trains are close, gatekeepers often hold the gate
   *and* extend the lead time. Today we merge windows but keep the single-train lead.
4. **Confidence calibration.** Verify that "80 % confident" is right 80 % of the time, and
   publish a reliability diagram. A confidence score nobody has validated is decoration.

## Then — the freight problem

Goods trains are the largest source of unexplained closures and no public source publishes them.
Three approaches, cheapest first:

1. **Statistical priors** (partly built) — learn per-crossing, per-hour unexplained-closure rates
   and expose them as a risk band.
2. **Crowd reports at scale** — the report button exists; the missing pieces are anti-abuse and a
   nudge at the right moment ("you're near the gate — what do you see?").
3. **A cheap physical sensor** — a solar magnetometer or IR beam by the track, reporting over
   LoRa/NB-IoT. This is the only way to make the app *observational* rather than predictive, and
   it changes the product category.

## Then — reach

- **Web Push notifications.** Schema and job stub are in place. Deliberately not shipped in v1:
  push demands trust we have not yet earned, and a wrong alert at 06:00 is worse than none. Gate
  this behind measured accuracy.
- **More crossings.** Adding one is already a `POST`. What is missing is a self-service flow for
  someone to submit their local gate, and an automated way to derive chainages from
  OpenRailwayMap geometry instead of by hand.
- **Multi-crossing routes.** "I'm driving from A to B and will cross three gates" is a different,
  harder, and more valuable question.
- **Hindi and regional languages.** The UI is deliberately word-light, which makes this cheap.
- **Home-screen widget / Android quick settings tile.** The ideal interaction is zero taps.

## Infrastructure, when the numbers demand it

| Trigger | Change |
|---|---|
| >1 API instance | Redis cache (implemented, one env var), scheduler on one process only |
| >100 crossings | Scheduler as a separate deployment, ingest sharded by railway zone |
| >1 000 crossings | Partition sightings/windows by month; Postgres read replica |
| National | Ingest becomes a stream, one consumer per zone. The prediction engine does not change — it is already a pure function |

## Explicitly not planned

- **A live train map.** It looks impressive and answers nobody's question. Other apps do it well.
- **Accounts and logins.** The app needs to know nothing about you.
- **Ads or tracking.** A utility people check for four seconds should cost them nothing, including
  attention.
- **An ML model before there is labelled data.** The learning engine *is* the model, incrementally
  and explainably. Revisit when a crossing has thousands of graded predictions and the residuals
  show structure that offsets cannot capture.
