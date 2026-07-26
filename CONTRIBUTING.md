# Contributing

Thanks for helping. This project is small, opinionated, and takes correctness seriously — a wrong
prediction sends someone into a twenty-minute queue at a level crossing.

## Ground rules

1. **Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) first**, especially the layering rules.
   Most review comments are just "this breaks the data-flow direction".
2. **The prediction engine stays pure.** No I/O, no clock reads, no globals. If you need data,
   pass it in.
3. **Business logic never imports a provider.** Everything downstream speaks `TrainSighting`.
4. **Ship a test that would have caught the bug**, not a test that documents the fix.
5. **Honesty over confidence.** Never make the app claim something it cannot support. If a
   change makes predictions look better without being better, it will be rejected.

## Getting started

```bash
make install
make test          # should be green before you touch anything
```

## Making a change

```bash
git checkout -b feat/short-description
make lint          # ruff + mypy + eslint + tsc
make test
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(providers): add NTES adapter
fix(prediction): stop double-counting delay when actuals are present
docs(api): document the advice block
```

## What we especially want

| Contribution | Why it matters |
|---|---|
| **Field-verified crossing geometry** | The seeded chainages for Siraspur are map estimates. Real surveyed numbers are the single highest-value contribution |
| **New crossings** | Send the bracketing stations, chainages and a local timetable |
| **Provider adapters** | More sources, less single-vendor risk |
| **Freight signal ideas** | The biggest open problem in the product |
| **Accessibility fixes** | This is used one-handed, outdoors, in sunlight |

## What we will push back on

- Adding a state-management or component library to a one-screen app
- Replacing the deterministic model with an opaque one before there is labelled data to justify it
- Anything that raises polling frequency without accounting for provider quota
- Scrapers of sites whose terms don't permit it (see [`docs/RESEARCH.md §3.1`](docs/RESEARCH.md))

## Pull requests

- Keep them focused; one idea per PR
- Say what you tested and how
- Screenshots for UI changes (light *and* dark, and a small viewport)
- If it changes prediction behaviour, include before/after numbers from
  `GET /crossings/{slug}/accuracy` or a reasoned argument

## Reporting a bad prediction

Open an issue with the crossing slug, the timestamp, what the app said and what actually
happened. If you can, attach the response body — `trace_id` lets us find the exact ingest tick.

## Security

Please do not open public issues for security problems. See [SECURITY.md](SECURITY.md).

## Code of conduct

Be decent. Assume good faith. Critique code, not people.
