# ADR 0001 — Provider abstraction with failover chain

**Status:** Accepted

## Context
Every available Indian Railways live-train source is either unofficial, rate-limited,
commercially fragile, or all three. Building business logic against any single one of them
guarantees a rewrite.

## Decision
Define a narrow domain object (`TrainSighting`) and a 3-method `TrainDataProvider` protocol.
All providers are ordered in a `FailoverChain` with per-provider circuit breakers, timeouts and
trust weights. The chain always terminates in a provider that cannot fail (`TimetableProvider`,
served from our own DB).

## Consequences
+ Adding/removing a source is a leaf change; no business logic is touched.
+ Provider trust flows into the confidence score, so a degraded source degrades the *claim*, not
  just the data.
+ Testing is trivial — the engine is tested against fabricated sightings, never HTTP.
− Normalisation code must be written per provider, and we lose provider-specific extras.
  Accepted: those extras are exactly what would couple us.
