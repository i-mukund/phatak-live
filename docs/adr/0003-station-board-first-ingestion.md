# ADR 0003 — Station-board-first ingestion under a request budget

**Status:** Accepted

## Context
RailRadar's free tier allows 50 requests/day. Per-train live polling needs ~2 000/day.

## Decision
Poll the two bracketing stations' live boards (2 calls/tick, independent of traffic volume) and
spend a small configurable budget of per-train live calls only on the trains nearest the
crossing. A token-bucket `ApiBudget` degrades to board-only mode before the quota is hit.

## Consequences
+ API cost scales with **track segments**, not trains or crossings — this is what makes national
  scale affordable.
+ Cost is bounded and predictable; 429s become rare rather than routine.
− Trains far from the crossing are predicted from schedule + delay only. Acceptable: precision
  only matters near the gate, and the blend weight already encodes that.
