# P11 Deployment Readiness

Scope: this document assesses whether the repository can be deployed and operated as
what it actually is — a self-contained, offline, single-tenant, single-process
identity-document verification **training/workshop service** — not whether it meets
the bar for a regulated, multi-tenant, high-volume production KYC system. See
`residual_risk_register.md` for what stands between this system and that latter bar.

## Runnable today, verified in this review

- **Local (no Docker)**: `python -m venv .venv && pip install -r requirements.txt &&
  python scripts/workshop_preflight.py && python -m uvicorn src.app:app` — verified
  from a genuinely fresh clone in this review (`test_evidence.md` §9), including a real
  Uvicorn process answering real `curl` requests.
- **Environment variables**: all optional, all with safe workshop defaults
  (`LOG_LEVEL`, `REVIEW_DB_PATH`, `REVIEWER_API_KEYS`, `REVIEW_RATE_LIMIT_MAX`,
  `REVIEW_RATE_LIMIT_WINDOW_SECONDS`) — the service runs with zero configuration, and
  every one was already externalized before this review (P10).
- **Process lifecycle**: startup eagerly opens the review store and verifies the
  dataset is readable, failing fast rather than accepting traffic and erroring on the
  first request; shutdown explicitly closes the SQLite connection. Both re-confirmed
  working via the clean-room live server run in this review.
- **Health/readiness/metrics**: `GET /health/live`, `GET /health/ready` (checks
  dataset, review store, and auth config, not just process liveness), `GET /metrics`
  (Prometheus-text) — all three re-verified live against a real server process in this
  review.
- **CI pipeline**: `.github/workflows/ci.yml` — lint, test (preflight + sanity + pytest
  + smoke + eval), security (`pip check` + `pip-audit`), build (`docker build`). Every
  command outside the `build` job was independently re-run and verified in this review;
  the `build` job and the workflow's own GitHub Actions execution remain unverified
  from within any session (no Docker daemon, no Actions runner available here).

## What changed in this review (P11)

One fix (`src/security/idempotency.py`, `src/app.py`) closing the concurrent
idempotency-key race described in `requirement_traceability.md` area 6. No deployment
configuration, environment variable, Dockerfile, or CI workflow content changed.

## Before this can be deployed beyond a single-process workshop instance

These are not required for the stated purpose of this repository, and are listed here
only so a future team scaling this beyond a workshop knows exactly what to replace and
where the seam already exists:

1. **Replace `RateLimiter`/`IdempotencyCache` with a shared-store implementation**
   (e.g. Redis) if running more than one process/replica — both already expose a
   narrow interface (`check()`, `get_or_compute()`) built for exactly this swap.
2. **Replace `ReviewStore` with a `ReviewRepository` implementation backed by a
   real database** (e.g. Postgres) if running more than one replica — the ABC
   (`src/review/store.py`) already isolates `src/app.py` from the storage choice.
3. **Run the CI pipeline for real** (GitHub Actions execution) at least once before
   trusting it as a release gate — every command in it has been individually verified
   to work, but the orchestration itself has not.
4. **Build and smoke-test the container image with a real Docker daemon** at least
   once — the Dockerfile was reviewed for correctness (non-root user, `HEALTHCHECK`,
   pinned `requirements.txt`-only deps) but never executed in any session to date.
5. **Decide on a real secrets-management story** for `REVIEWER_API_KEYS` in any
   environment where `config/security.json`'s workshop default would otherwise be
   mistaken for a real credential (it is clearly labeled, but labels are not a control).

## Rollback / redeploy notes

The stateless verify endpoints (`/v1/documents/verify`, `/v1/cases/{id}/verify`) have
no state to roll back — redeploying an older container/process is safe at any time. The
only stateful component is the review workflow's SQLite file
(`var/review_store.sqlite3` by default); rolling back application code while that file
already contains rows written by newer code could surface schema drift if a future
change ever alters the `review_cases`/`review_audit_log` schema — no migration
tooling exists today because no schema change has yet occurred since the table was
introduced in P6. This is a real gap for a future schema change, not a gap today.
