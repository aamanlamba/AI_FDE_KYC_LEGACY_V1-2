# Deployment & Environment — Stage P10

## Running locally (no Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts/workshop_preflight.py
python -m uvicorn src.app:app --host 0.0.0.0 --port 8000
```

## Running via Docker

```bash
docker build -t ai-fde-kyc .
docker run --rm -p 8000:8000 ai-fde-kyc
```

The image (stage P10 hardening): runs as a non-root user (`appuser`, uid 1000), has a
`HEALTHCHECK` that exercises the same dependency checks as `GET /health/ready` (not
just process liveness), and installs only `requirements.txt` (never
`requirements-dev.txt` — lint/security tooling stays out of the runtime image). **Not
build-tested in this environment**: no Docker/Podman daemon is available here (true
since P0's original packaging — see `docs/qa_release_report.md`); the Dockerfile was
reviewed but not executed. `docker build` is included as a CI job
(`.github/workflows/ci.yml`) that does run it with real Docker.

## Environment variables

All optional; every one has a safe workshop default so the service runs with zero
configuration.

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root logger level for structured JSON logs |
| `REVIEW_DB_PATH` | `var/review_store.sqlite3` | SQLite file location for the review workflow |
| `REVIEWER_API_KEYS` | (from `config/security.json`) | Comma-separated reviewer credentials; **replaces**, not merges with, the config file default |
| `REVIEW_RATE_LIMIT_MAX` | `20` | Max review transitions per credential per window |
| `REVIEW_RATE_LIMIT_WINDOW_SECONDS` | `60.0` | Rate-limit window size |

## Configuration files

| File | Purpose | Committed? |
|---|---|---|
| `config/baseline.json` | Business policy values (mandatory fields, supported document types, completeness threshold) | Yes — non-secret |
| `config/security.json` | Workshop-only reviewer credentials, clearly labeled as such | Yes — explicitly not a real secret; a real deployment overrides via `REVIEWER_API_KEYS` |

## Resource/state directories

| Path | Contents | In version control? |
|---|---|---|
| `data/` | Synthetic fixtures (applications, ground truth, OCR sidecars, images, golden snapshots) | Yes |
| `var/` | Runtime state: the review SQLite database, evaluation reports | No (gitignored) — this is where real PII would accumulate in a non-training deployment; see `docs/security/privacy_data_flow.md` for retention/deletion |

## Process lifecycle (P10 requirement 10)

- **Startup**: `src/app.py`'s `lifespan` handler eagerly opens the review store's
  SQLite connection (runs schema migration if needed) and verifies the dataset is
  readable, logging a structured `startup` event — failing fast if either is broken,
  rather than accepting traffic and erroring on the first request.
- **Shutdown**: the review store's SQLite connection is closed explicitly (not left to
  process exit / garbage collection), logging a structured `shutdown` event.
- **Readiness**: `GET /health/ready` re-checks the same dependencies on every call
  (not just at startup) — see `docs/operations/runbook.md` Diagnostic 1.

## Scaling notes (read `docs/architecture/overview.md`'s concurrency section first)

This is a single-process service today. `src/review/store.py`'s SQLite access is
lock-serialized within one process — running multiple replicas each with their own
`REVIEW_DB_PATH` would silently split review state across untied SQLite files, which
is **not** supported without first implementing a shared `ReviewRepository`
(Postgres/etc., see ADR-003) behind the same interface. The stateless verify endpoints
have no such constraint and can be horizontally replicated as-is.

## Health/metrics for a load balancer or orchestrator

- Liveness probe: `GET /health/live` (process is up).
- Readiness probe: `GET /health/ready` (dependencies verified — see
  `docs/data_dictionary.md`'s observability section for the `checks` shape).
- Metrics scrape target: `GET /metrics` (Prometheus-text-compatible, unauthenticated).

## CI pipeline

`.github/workflows/ci.yml` — four jobs: lint (`ruff` + `compileall`), test (preflight +
sanity + pytest + smoke + eval, all against a fresh checkout), security (`pip check` +
`pip-audit`), build (`docker build`). Every command in the lint/security jobs was
verified to run successfully in this development environment before being added to
the workflow (see this stage's session log / `docs/architecture/adr/ADR-007-*.md`);
the workflow itself has not been executed by GitHub Actions from within this session.
