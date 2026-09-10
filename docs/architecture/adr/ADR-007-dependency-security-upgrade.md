# ADR-007: Upgrade fastapi/starlette/pytest after a real `pip-audit` finding

**Status**: Accepted (P10)

## Context
P10 requirement 19 asked for dependency/security checks. Running `pip-audit
-r requirements.txt` (network-accessible in CI, distinct from the application's own
offline runtime requirement) found 6 known CVEs: 5 in `starlette` (an unpinned
transitive dependency `fastapi==0.128.2` forced to `<0.51.0`) and 1 in
`pytest==9.0.2`.

## Decision
Upgrade `fastapi` to `0.141.1` (which permits a patched `starlette>=1.0`), pin
`starlette==1.6.0` directly rather than leaving it an implicit transitive dependency,
upgrade `uvicorn` to `0.52.4` for compatibility, and upgrade `pytest` to `9.1.1`.

## Consequences
- Verified, not assumed: `pip install --upgrade starlette` alone failed with a
  dependency-conflict error against the old pinned `fastapi==0.128.2` (which caps
  starlette below `0.51.0`) — the fix required upgrading fastapi first. The full
  regression suite (219 tests at the time), `scripts/workshop_preflight.py`,
  `scripts/sanity_check.py`, `scripts/smoke_server.py` (a real live Uvicorn process),
  and `scripts/run_evaluation.py`'s release gates all passed unchanged after the
  upgrade — re-run `pip-audit -r requirements.txt` afterward: zero known
  vulnerabilities.
- `requirements-dev.txt` (new in P10) keeps `ruff`/`pip-audit` out of the runtime
  image entirely — the application's own offline-at-runtime guarantee is unaffected
  by CI tooling needing network access to install and query vulnerability databases.
- `scripts/workshop_preflight.py`'s `REQUIRED` version table was updated to match, so
  the workshop's own "release-tested versions detected" check reflects the new
  baseline rather than perpetually warning about a version mismatch.
