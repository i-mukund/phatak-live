# Developer Guide

## Getting set up

```bash
make install          # backend (editable + dev extras) and frontend deps
make test             # 159 tests, ~3 seconds
make dev-api          # http://localhost:8000  (docs at /docs)
make dev-web          # http://localhost:3000
```

No API key needed: with `RAILRADAR_API_KEY` unset the mock provider is promoted to primary and
generates a deterministic Siraspur-like traffic pattern.

## The mental model

Data flows one way. Nothing further left in this list may import anything further right.

```
providers  →  domain objects  →  prediction engine  →  services  →  API  →  frontend
                                        ↑
                                  learning engine (writes calibration, never called by the engine)
```

Concretely:

- `app/domain.py` imports nothing from the app.
- `app/providers/*` may import `domain` and `core`. **Never** `services` or `db.models`.
- `app/services/prediction/*` is pure: no I/O, no `datetime.now()`, no globals.
- `app/services/{ingest,status_service}.py` own all persistence and orchestration.
- `app/api/*` is thin: validate, delegate, serialise.

If a change makes you want to break one of these, the design is telling you something.

## Where things live

| I want to… | Go to |
|---|---|
| Add a data source | `app/providers/` + register in `registry.py` |
| Change how a pass time is computed | `app/services/prediction/geometry.py` |
| Change gate open/close physics | `app/services/prediction/engine.py` (`gate_close_lead_seconds`, `gate_clear_seconds`) |
| Change how windows merge | `merge_windows()` in the same file |
| Change the confidence formula | `app/services/prediction/confidence.py` |
| Change what the learning loop does | `app/services/learning/engine.py` |
| Add a field to the status payload | `app/schemas/status.py` + `app/services/status_service.py` + `frontend/src/lib/types.ts` |
| Add a crossing | `POST /api/v1/crossings` — no code |
| Change a default | `app/core/config.py` only |

## Adding a provider — the whole job

1. **Implement the protocol** (`app/providers/base.py`):

```python
class MyProvider(BaseProvider):
    name = "my_provider"
    trust = 0.7                      # flows straight into the confidence score

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        payload = await self._client.get_json(f"/trains/near/{ctx.crossing.prev_station_code}")
        return [self._parse(record, ctx) for record in payload["items"]]
```

   Raise `ProviderError` on failure — never return partial garbage. Mark non-retryable errors
   (`retryable=False`) so retries do not burn quota on a 401.

2. **Register it** in `app/providers/registry.py` with a tier:

```python
registered.append(RegisteredProvider(MyProvider(...), ProviderTier.PRIMARY, breaker("my_provider")))
```

3. **Add its settings** to `app/core/config.py`.

4. **Write a contract test** against a recorded payload (see `tests/test_providers.py`). That
   test is your early warning when the vendor changes their schema.

Nothing else changes. Failover, circuit breaking, timeouts, retries, dedup and metrics are the
chain's job.

### Emitting sightings

Rich providers return a normalised `route` plus a `LivePosition`; the shared geometry resolver
handles the rest. Simple providers can set `direct_pass_estimate` and skip routes entirely.
RailRadar does something in between: it builds a **synthetic two-stop route** using the crossing's
own station codes so board-derived data flows through exactly the same code path as full live
data. Copy that pattern — it is why there is only one geometry implementation.

## Testing

```bash
make test                                    # everything
pytest tests/test_prediction.py -q           # one file
pytest -k "freight or merge" -q              # by name
make cover                                   # htmlcov/index.html
make load                                    # locust profile
```

Conventions that keep the suite fast and honest:

- **The engine is tested with plain data**, never mocks — see `tests/factories.py`.
- **Time is injected.** `FrozenClock`, and `now` is a fixture. No `freezegun`, no sleeping.
- **Failure modes have tests**, one per row of the ARCHITECTURE failure table
  (`tests/test_resilience.py`).
- **Providers are tested against recorded payloads** via `respx`; no test touches the network
  (`conftest.py` even strips proxy env vars to guarantee it).

Adding behaviour without a test that would have caught the bug is not done.

## Frontend notes

- One screen, one endpoint. There is no state-management library on purpose — `useLiveStatus`
  is 90 lines and does exactly three things (visibility-aware polling, exponential backoff, and
  never clearing good data on error).
- **Countdowns are computed on the client** from absolute timestamps. If you ever find yourself
  wanting a server-sent duration, re-read the caching section of ARCHITECTURE.md.
- Direction labels come from `crossing.up_towards` / `down_towards`, so no component contains
  the word "Panipat".
- `npm run typecheck && npm run lint && npm run build` must all pass; CI runs them.

## Code style

- Python: `ruff` (100 cols) + `mypy`. Full type annotations on public functions.
- Docstrings explain *why*, not *what* — the code already says what.
- TypeScript: `strict` plus `noUncheckedIndexedAccess`.
- Comments earn their place by capturing a decision, a trap, or a non-obvious constraint.

## Common pitfalls

| Trap | Guard |
|---|---|
| Double-counting delay when actual times already include it | `_schedule_estimate` only adds `delay_minutes` when neither anchor has actuals — there is a test |
| Naive datetimes | `UtcDateTime` coerces on the way in and out; `ensure_aware` everywhere else |
| Calling a provider from a request handler | Don't. The read path is DB-only by design |
| Polling more often to "improve accuracy" | It multiplies API spend without improving anything — the upstream refresh rate is the limit |
| Trusting `speedKmh` blindly | Clamped to 8–180 km/h; a zero or a 999 poisons the whole window |

## Releasing

1. `make lint && make test`
2. Update `VERSION` in `app/api/v1/health.py` and the CHANGELOG entry
3. Tag; CI builds and smoke-tests both images
4. Deploy; watch `phatak_prediction_error_seconds` for a day
