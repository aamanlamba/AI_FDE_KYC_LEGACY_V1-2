# P11 — Production Readiness, Red-Team & Final Engineering Review

## Purpose and method

This review treated P1–P10's own reports as claims to be independently re-verified,
not facts to be restated. Every finding below was produced by actually running the
system in this session — live API calls through the real FastAPI/ASGI stack, direct
module calls, the independent eval harness, a real Uvicorn process answering real HTTP
requests, and a genuinely fresh `git clone` into an isolated environment — not by
re-reading prior stages' self-reports. Full command output is in
[test_evidence.md](test_evidence.md).

## What this review did

1. **Requirement traceability** ([requirement_traceability.md](requirement_traceability.md)):
   re-classified all 10 capability areas from P1–P10 as PASS/PARTIAL/FAIL/NOT_APPLICABLE
   against live evidence. Result: 9/10 areas PASS outright; 1/10 (HITL review) PASS
   with one genuine defect found and fixed during this review.
2. **Red-team probe**: 27 adversarial checks fired directly at the live system —
   malformed requests, unknown resources, a provider returning a contract-violating
   payload, an unsupported document type, real contradictory/OCR-corrupted identity
   evidence, malformed dates, expired/tampered documents, missing-evidence documents,
   duplicate/repeated reviewer actions, simulated provider timeouts, log/control-character
   injection attempts, path traversal, oversized inputs, and concurrency. **One genuine
   defect found**: a narrow race in the idempotency-key mechanism (detailed below).
   All 27 checks pass after the fix, confirmed across 3 consecutive re-runs.
3. **Decision-safety invariants** (8) and **privacy/security invariants** (7): all 16
   verified directly against live case data and direct module calls — no APPROVE
   bypasses validation, fraud/document hard-stops reach REJECT, missing evidence never
   silently passes, fuzzy matching stays structurally distinct from an exact match, no
   LLM dependency exists anywhere, REVIEW cases carry real evidence, every risk
   factor's reason code is traceable to that factor's own hard-stop status, decisions
   are reproducible under a fixed trace context, no PII leaked into a captured log
   stream, reviewer endpoints reject missing/wrong credentials, a malformed provider
   payload is rejected at construction, no `eval`/`exec` of untrusted content exists,
   path traversal is blocked at the repository layer, no real secrets are embedded, and
   a forced 500 leaked no internal detail. **16/16 pass.**
4. **Full verification suite re-run**: 222 unit/integration tests, `ruff` (clean),
   `pip-audit` (0 known vulnerabilities), workshop preflight/sanity/smoke, and the eval
   harness's 6 release gates — all re-run and passing, both in this development
   environment and independently from a fresh clone.
5. **Performance probe**: real, local, single-process latency/throughput numbers
   captured with full environment disclosure and explicitly no extrapolation to
   production capacity ([test_evidence.md](test_evidence.md) §8).
6. **Clean-room verification**: a genuine `git clone` into an isolated directory with a
   brand-new virtualenv reproduced the entire documented chain from zero — install,
   preflight, sanity, 222 tests, smoke, eval gates — and then a real (not `TestClient`)
   Uvicorn process was started from that clean clone and exercised with real `curl`
   requests end-to-end, including a case that reaches REVIEW with a full decision
   lineage, and a reviewer-authenticated review-open call.

## The one genuine defect found, and its fix

**Finding**: `IdempotencyCache`'s `get()`/`put()` sequence around the review-transition
endpoint was not atomic. Firing concurrent retries of the same request with an
identical `Idempotency-Key` could let a retry land in the window between another
thread's database commit and its cache write, causing the retry to re-run the
transition against already-mutated state and receive a spurious `409` instead of the
cached success. No duplicate side effect ever occurred (the audit log stayed
single-entry in every observed case) — the defect was in the idempotency guarantee
itself, not in data integrity.

**Fix**: `IdempotencyCache.get_or_compute()` now holds one lock across the entire
check-compute-store sequence, so concurrent retries of the same key serialize instead
of racing into the store. `src/app.py`'s `transition_review` was updated to use it.

**Re-verification**: a new concurrent regression test (8 parallel identical-key
requests, asserting zero errors and exactly one audit entry) was added and passes; the
full 222-test suite, `ruff`, and `pip-audit` all pass unchanged; the original 5-worker
race scenario was re-run 3 times consecutively with zero failures after the fix (it was
intermittent before). This is a real, fixed, and re-verified change — not a
documentation update. See [test_evidence.md](test_evidence.md) §7 for full before/after
evidence and [requirement_traceability.md](requirement_traceability.md) area 6.

## What this review deliberately did not change

No decisioning logic, validation rule, fraud signal, identity-matching threshold, API
contract, or configuration default was touched. This review's mandate was verification
and fixing genuinely demonstrated defects — not re-opening design decisions already
made and tested in P1–P10 without new evidence that they are wrong. None of the 16
invariant checks or 27 red-team checks surfaced a design defect beyond the one
concurrency issue above.

## Final release classification

# **READY WITH CONDITIONS**

**Rationale**: Per the P11 final rule, "all unit tests pass" is explicitly not treated
as sufficient grounds for a bare READY. This review independently re-verified
correctness (16/16 invariants, 27/27 red-team checks, 222/222 tests), safety (no
decision-safety or privacy invariant violated), traceability (every decision explains
itself from retained evidence, live-verified), operability (structured logs, spans,
metrics, health checks all reconstructable without reading source, live-verified), and
reproducibility (a genuine clean-room clone reproduces the entire chain, including a
real live server, from zero). One genuine defect was found and fixed in place, with its
own regression test, during this review — not deferred.

The **conditions** are exactly the items in
[residual_risk_register.md](residual_risk_register.md) that remain true by design, not
by oversight: this is a single-process service (in-memory rate limiter and idempotency
cache, SQLite-backed review store) appropriate for its stated purpose as an offline
training/workshop KYC system; it has never claimed — and this review does not grant it
— readiness for multi-replica, high-volume, or regulated production KYC deployment
without the seam-based upgrades listed in
[deployment_readiness.md](deployment_readiness.md) (shared-store rate limiting/idempotency,
a `ReviewRepository` implementation backed by a real database, an actual executed CI
run, and an actual executed container build/smoke test). None of these are defects;
all of them are pre-existing, honestly disclosed scope boundaries that this review
re-confirmed rather than newly discovered.

**For its stated purpose — a self-contained, offline, reproducible KYC verification
training system — this repository is release-ready as of commit `25b8854`.**
