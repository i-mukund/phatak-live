# Security Policy

## Reporting a vulnerability

Please report privately — open a GitHub security advisory, or email the maintainers. Do not open
a public issue.

Include what you found, how to reproduce it, and what an attacker could do with it. We will
acknowledge within 72 hours and keep you updated until it is resolved.

## Scope and threat model

Phatak Live stores no personal data, has no user accounts, and holds nothing worth stealing
except its API keys. The realistic risks are:

| Risk | Mitigation |
|---|---|
| API key leakage | Keys live only in environment variables; `.env` is git-ignored; `render.yaml` marks them `sync: false` |
| Unauthenticated writes | `POST /crossings` and all `/admin/*` require `X-Admin-Key` and **fail closed** in production when it is unset |
| Crowd-report abuse | Reports are advisory: the learning engine discards residuals beyond 45 minutes and uses EWMA, so a burst of bad reports cannot swing calibration far or fast |
| Upstream data poisoning | All provider input is parsed defensively; speeds are clamped; malformed records are dropped, not trusted |
| Resource exhaustion | Response caching, per-provider timeouts, circuit breakers, a daily upstream budget, and data retention |
| Dependency vulnerabilities | Dependabot-friendly pinning, CodeQL on every PR and weekly |

## Hardening notes for operators

- Always set `ADMIN_API_KEY` in production, and set `CORS_ORIGINS` to your exact frontend origin.
- Terminate TLS in front of both services; the backend runs with `--proxy-headers`.
- Both containers run as non-root (uid 10001) with no build toolchain in the runtime layer.
- Put a rate limiter in front of `POST /crossings/{slug}/reports` if you get real traffic; it is
  the only unauthenticated write endpoint.

## Safety, not security

A separate but more important point: **this software must never be used to decide whether it is
safe to cross a railway line.** It predicts; it does not observe. Treat any suggestion to the
contrary as a bug and report it.
