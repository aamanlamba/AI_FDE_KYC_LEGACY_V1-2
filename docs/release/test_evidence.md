# P11 Test Evidence

Every result below was executed in this review, not carried forward from prior stages'
self-reports. Commands are given verbatim so they can be reproduced. Two environments
were used: (a) this development environment's existing `.venv`, and (b) a genuinely
fresh `git clone` into an isolated directory with a brand-new `.venv`, to rule out
"works only because of accumulated local state" (Phase 7, clean-room verification).

## 1. Regression suite (existing environment, after the P11 fix)

```
python -m pytest -q
```
Result: **222 passed, 2 warnings** (the 2 warnings are pre-existing, known,
non-actionable deprecation notices from `starlette`/`anyio`, unrelated to this
repository's code — documented since P9/P10).

Before the P11 fix: 219 passed (the P10 baseline). After adding 3 new tests
(`test_concurrent_retries_with_the_same_idempotency_key_never_409`,
`test_idempotency_cache_get_or_compute_runs_compute_once_per_key`,
`test_idempotency_cache_get_or_compute_does_not_cache_a_failure`): 222 passed.

## 2. Lint and dependency audit

```
ruff check src/ tests/ eval/ scripts/     → All checks passed!
pip-audit -r requirements.txt              → No known vulnerabilities found
```
(One transient `ruff` finding — `E731` on the idempotency fix's first draft, a lambda
assignment — was fixed by rewriting it as a `def` before this was recorded as clean.)

## 3. Workshop sanity/preflight/smoke

```
python scripts/workshop_preflight.py   → PREFLIGHT PASSED
python scripts/sanity_check.py         → SANITY CHECK PASSED: 6 cases, 13 documents, ...
python scripts/smoke_server.py         → SMOKE SERVER PASSED on ephemeral localhost port ...
```

## 4. Evaluation harness (release gates)

```
python scripts/run_evaluation.py
```
```
Document Intelligence: exact_match=0.9762 (82/84), F1=1.0
Identity Resolution: match_status_accuracy=1.0 (8/8), conflict_detection_accuracy=1.0 (3/3)
Decisioning: decision_accuracy=1.0 (10/10), FA=0/3, FR=0/3, review_rate=0.6364
Operations: STP_rate=0.5 (3/6), error_rate=0.0, latency_median_ms≈0.35
Metamorphic: invariance=4/4, adversarial_sensitivity=3/3
RELEASE GATE STATUS: PASS  (6/6 gates)
```
Sample-size caveat (carried from P7, still accurate): 11 labeled eval cases is a
demonstration-scale set, not a statistically powered production sample — accuracy
figures should be read as "0 known failures on the curated case set," not as a
calibrated population error rate.

## 5. Red-team probe (Phase 2) — 27/27 checks, run against the live FastAPI app

Fired directly at `TestClient(app)` (full ASGI stack, not bypassing it): malformed
JSON/missing fields/wrong types (422), unknown document/case ids (404), a provider
returning a wrong-shaped object (`ProviderContractError`), an unsupported document type
(flagged `DOCTYPE-SUPPORTED: FAIL`), CASE-005's real contradictory/OCR-corrupted
identity (`CONFLICT`, corrupted value preserved verbatim not silently corrected), a
malformed date (fails safely, no exception), CASE-004 (expired → REJECT), CASE-006
(tamper marker → REJECT), a document missing all mandatory fields (3 `MANDATORY-*: FAIL`
results, not silently passed), duplicate review-open (idempotent), a repeated identical
reviewer transition (409 on the second), a simulated provider timeout
(`ProviderUnavailableError` after retries exhausted), hostile control-character/log-injection
text (`sanitize_for_display` strips newlines/NUL/ANSI), 5 path-traversal/oversized-id
variants (400/422), an oversized rationale (422), 30 concurrent case-verify calls
(0 errors), review-open correctly refused for a REJECT-decision case (409), and 5
concurrent identical-idempotency-key transition requests (all 200, one audit entry —
after the fix; **before the fix this was the one place a genuine defect showed up**, see
§7 below).

Result: **27/27 passed** (re-run 3 times consecutively after the fix to confirm the
race no longer reproduces).

## 6. Decision-safety and privacy/security invariants (Phases 3 & 4) — 16/16 checks

All 8 decision-safety invariants and all 7 privacy/security invariants (plus one
combined check) verified directly against live case data and direct module calls:
- No APPROVE decision across any of the 6 real cases carries a `FAIL` validation result.
- CASE-006's fraud hard-stop reaches REJECT (not overridden by anything downstream).
- The eval harness's independent zero/insufficient-evidence case (`EVAL-MISSING-EVIDENCE-01`)
  resolves to REVIEW with `identity_overall_status=INSUFFICIENT_EVIDENCE`, never APPROVE.
- `FUZZY_MATCH` is confirmed structurally distinct from `MATCH` (`STATUS_RANK`).
- No LLM import/dependency anywhere (see requirement_traceability.md area 4).
- CASE-005 (REVIEW) carries non-empty `reason_codes` and `risk_factors`.
- Every risk factor's category is represented in `reason_codes` as
  `{HARD_STOP|REVIEW}:{category}` per that factor's own `triggers_hard_stop`, across
  all 6 real cases.
- `verify_case("CASE-005")` called twice inside one bound trace context produces a
  byte-identical `model_dump()`.
- A real name value from a live response was confirmed absent from captured log text.
- Reviewer endpoints reject no-credential and wrong-credential requests (401).
- A malformed-enum `DocumentEvidence` construction raises a Pydantic `ValidationError`.
- No `eval(`/`exec(` of untrusted content anywhere in `src/`.
- `safe_id("../../etc/passwd")` raises, confirmed at the repository layer directly.
- No real secret patterns/PEM keys in `src/` or `config/`.
- A forced internal 500 (dependency raising `RuntimeError` with an embedded path) leaks
  neither the exception type nor the embedded path to the caller.

Result: **16/16 passed** (one script-methodology error was found and corrected along
the way — an initial LLM-grep false-positive on a docstring, and an initial
reason-code/reproducibility check that made a wrong assumption about response shape;
both were root-caused and fixed in the *test script*, not the system, before being
recorded as passing — see the commit history of this review's scratch scripts for the
full before/after).

## 7. P11 fix verification (the one genuine defect found)

**Before the fix**, running 5 concurrent transition requests with the same
`Idempotency-Key` against a fresh review produced `[200, 200, 200, 200, 409]` — one
request received a 409 rather than the cached success, even though only one audit-log
entry was ever written (no duplicate side effect, but a broken idempotency contract).
Root cause: `get()` and `put()` on `IdempotencyCache` were separate, unlocked-across
operations around the mutating `store.apply_transition()` call.

**Fix**: `IdempotencyCache.get_or_compute(key, compute)` holds one lock across the
entire check-compute-store sequence (`src/security/idempotency.py`); `src/app.py`'s
`transition_review` now calls it instead of manual `get()`/`put()`.

**Re-verification after the fix**:
- The same 5-concurrent-request scenario: `[200, 200, 200, 200, 200]`, one audit entry.
- New regression test with 8 concurrent workers
  (`tests/test_architecture.py::test_concurrent_retries_with_the_same_idempotency_key_never_409`):
  passes.
- Full suite re-run: 222/222 passed.
- Red-team probe re-run 3 times consecutively: 27/27 each time (the race was
  intermittent under 5 workers; repetition matters for confidence — see §5).
- `ruff`/`pip-audit`: clean after the fix.

## 8. Performance probe (Phase 6) — local, in-process, explicitly not a capacity claim

Environment: `macOS-26.6.2-arm64-arm-64bit-Mach-O`, Python 3.14.7, single process,
`TestClient` (in-process ASGI, no real network socket), SQLite review store,
deterministic offline providers. 200 requests per measurement after a 10-request warm-up.

| Endpoint | Throughput | p50 | p95 | p99 |
|---|---|---|---|---|
| `GET /v1/cases` | 1149 req/s | 0.86ms | 0.94ms | 1.06ms |
| `POST /v1/documents/verify` | 957 req/s | 1.02ms | 1.21ms | 1.33ms |
| `POST /v1/cases/{id}/verify` (round-robin, all 6 cases) | 805 req/s | 1.22ms | 1.38ms | 1.48ms |
| `GET /health/ready` | 1157 req/s | 0.85ms | 0.95ms | 1.04ms |
| `GET /metrics` | 1323 req/s | 0.75ms | 0.81ms | 0.93ms |

8-worker concurrent `POST /v1/cases/{id}/verify` (200 requests): 697.8 req/s, 0 errors —
**lower** than single-threaded throughput, because `TestClient`'s in-process dispatch is
CPU-bound under Python's GIL; this measures request-handling overhead, not what a real
multi-worker Uvicorn/Gunicorn deployment behind a real socket would achieve under
concurrent I/O-bound load. No extrapolation to "production capacity" is made from these
numbers — they establish that per-request overhead is on the order of ~1ms for this
dataset size (6 cases, 13 documents) and that the code path has no obvious
O(n²)/synchronous-blocking landmine, nothing more.

## 9. Clean-room verification (Phase 7)

A fresh `git clone` (not a copy of the working tree) of the local repository at commit
`25b8854` ("P11 — fix concurrent idempotency-key race found during red-team review")
into an isolated directory, with a brand-new virtualenv, reproduced the full documented
chain from zero:

```
python3 -m venv .venv && pip install -r requirements.txt   → clean install
python scripts/workshop_preflight.py                        → PREFLIGHT PASSED
python scripts/sanity_check.py                               → SANITY CHECK PASSED
python -m pytest -q                                           → 222 passed, 2 warnings
python scripts/smoke_server.py                                → SMOKE SERVER PASSED
python scripts/run_evaluation.py                               → RELEASE GATE STATUS: PASS
```

Then a **real** Uvicorn process (not `TestClient`) was started from the clean clone,
bound to a real localhost port, and exercised with real `curl` HTTP requests:
`GET /health/live` → `{"status":"ok"}`; `GET /health/ready` →
`{"status":"ready","offline_ocr":true,"dataset_cases":6,"checks":{"dataset":"ok","review_store":"ok","auth_config":"ok"}}`;
`GET /v1/cases` → all 6 cases listed; `POST /v1/documents/verify` (CASE-001-PASSPORT) →
full evidence/validation payload, `APPROVE`; `POST /v1/cases/CASE-005/verify` → full
case payload including `identity_resolution.overall_status=CONFLICT`,
`risk_assessment.policy_outcome=REVIEW`, and a complete `decision_lineage` block;
`POST /v1/cases/CASE-005/reviews` with the workshop reviewer credential → a new
`ReviewCase` opened (`status=OPEN`, non-empty `reviewer_summary`); `GET /metrics` →
well-formed Prometheus-text output. The server was then cleanly stopped.

This confirms the repository is genuinely self-contained and reproducible from a fresh
checkout — not dependent on this development environment's accumulated state (installed
packages beyond `requirements.txt`, stray files, or a pre-populated `var/` directory).

**Not executable in this environment** (true since P0, re-confirmed, not re-attempted
here since nothing changed): Docker/Podman daemon is unavailable, so `docker build`/
container smoke test could not be run locally. `.github/workflows/ci.yml` runs
`docker build` as a real CI job; that workflow itself has not been executed by GitHub
Actions from within any session to date — reviewed, not executed.
