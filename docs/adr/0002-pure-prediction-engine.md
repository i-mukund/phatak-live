# ADR 0002 — The prediction engine is a pure function

**Status:** Accepted

## Context
Prediction correctness is the product. Anything that makes it hard to test, reason about, or
reproduce is an existential risk.

## Decision
`PredictionEngine.predict(now, crossing, sightings, profile) -> Prediction` performs **no I/O**,
reads **no clock**, and touches **no globals**. `now` is injected. All persistence, caching and
network access lives in services that call it.

## Consequences
+ Every scenario (two trains, delayed train, stale data, missing route) is a table-driven unit
  test with zero mocking.
+ Deterministic replay: a stored sighting snapshot reproduces a past prediction exactly, which
  makes the learning engine auditable.
+ Horizontal scaling is trivial (§9 of ARCHITECTURE.md).
− Callers must thread `now` and the calibration profile explicitly. Small price.
