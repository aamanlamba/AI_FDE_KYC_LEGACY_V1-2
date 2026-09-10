# P11 Residual Risk Register

Every item here is a **known, disclosed** limitation, not a defect discovered and left
unfixed. The one genuine defect found during this review (the idempotency-cache
concurrency race) was fixed in place — see
[requirement_traceability.md](requirement_traceability.md) area 6 and
[test_evidence.md](test_evidence.md) §7 — and does not appear here. Severity is scored
against this system's stated purpose (a locally-runnable training/workshop KYC
service), not against a hypothetical regulated production deployment of unbounded
scale, which this repository has never claimed to be.

| # | Risk | Severity | Root cause / why it exists | Mitigation status | Verification |
|---|---|---|---|---|---|
| 1 | Rate limiter and idempotency cache are in-memory, single-process | MEDIUM | `src/security/limits.py`/`idempotency.py` were built as "clearly testable integration points" (P8/P10 requirement), not distributed primitives; a real Redis-backed implementation was explicitly deferred | Documented in `docs/operations/deployment.md` scaling notes; interface shape (`check()`/`get_or_compute()`) is stable so a shared-store implementation is a drop-in replacement, not a redesign | `tests/test_security.py`, `tests/test_architecture.py` (concurrency tests exist only for the single-process case, by design) |
| 2 | Review store (SQLite) is single-writer, single-process | MEDIUM | `ReviewStore` holds one connection guarded by a `threading.Lock`; running multiple replicas each with their own `REVIEW_DB_PATH` would silently split review state | `ReviewRepository` ABC (P10) exists specifically so a Postgres-backed implementation can replace `ReviewStore` without touching `src/app.py` or `src/review/workflow.py` | `docs/architecture/overview.md` concurrency section; `docs/operations/deployment.md` scaling notes |
| 3 | No cryptographic checksum/signature verification | LOW (disclosed capability boundary, not a gap hidden from evidence) | This repository's OCR layer never reads image pixels or embedded signatures; no such capability was ever claimed | Every validation report literally states `CHECKSUM-SIGNATURE: NOT_IMPLEMENTED` with an explanatory `reason_code` — verified present in every live case response in this review, never silently dropped | `tests/test_evidence_validation.py`; live-verified in this review (§test_evidence.md #6) |
| 4 | Fraud/tamper detection is a literal synthetic-marker text match, not real forensics | LOW (disclosed) | No image-pixel inference exists anywhere in this system (stated repository purpose: deterministic offline training data) | `DocumentForensicsProvider` interface exists so a real forensics provider could be substituted; current provider's docstring and `docs/known_limitations.md` are explicit about the boundary | `tests/test_fraud_signals.py` |
| 5 | Confidence/evidence-strength scores are heuristics, not calibrated probabilities | LOW (disclosed) | `evidence_strength`/`uncertainty` in `RiskAssessment` are a completeness-ratio-derived heuristic by design (P5 requirement: avoid opaque scoring, prefer inspectable rules) | Explicitly documented as such in `docs/data_dictionary.md` and `docs/known_limitations.md`; the decision policy never treats these as probabilities in a threshold comparison | `tests/test_decision_policy.py` |
| 6 | Eval harness sample size (11 labeled cases) is demonstration-scale | LOW (disclosed, inherent to a training repo) | The dataset itself is synthetic and small by design | `sample_size_disclaimer` is emitted in every eval report and was not stripped or hidden in this review's re-runs | `var/eval/report.json`, re-run in both environments in this review |
| 7 | No tenant isolation | LOW (out of scope, stated) | This is a single-tenant workshop service; multi-tenancy was never a requirement in any P0–P10 prompt | Documented as an explicit non-goal in `docs/known_limitations.md` | N/A |
| 8 | `ReviewStore.purge_review()` has no API endpoint | LOW | P8 built the hard-delete primitive but deliberately did not expose it via HTTP (no authenticated "admin" tier existed at the time) | Documented as a deliberate, not accidental, scope boundary in `docs/security/privacy_data_flow.md` §4; the primitive itself is tested and working | `tests/test_security.py` |
| 9 | Docker build / container smoke test not executed in this development environment | LOW | No Docker/Podman daemon available here, true since P0 | `.github/workflows/ci.yml`'s `build` job runs `docker build` with real Docker; the Dockerfile itself was reviewed (non-root user, `HEALTHCHECK`, pinned deps) but not locally executed | Not independently re-verifiable in this environment; unchanged since P10 |
| 10 | CI pipeline (`.github/workflows/ci.yml`) has never actually been run by GitHub Actions | LOW | No GitHub Actions execution available from within any session to date | Every command the workflow runs was individually verified to succeed in this environment (lint, tests, `pip-audit`) — only the orchestration itself (the YAML, runner environment) is unverified | N/A |
| 11 | `/v1/documents/verify` and `/v1/cases/{id}/verify` remain unauthenticated | LOW (documented, deliberate) | P8 threat model §10 scoped authentication to reviewer-mutation endpoints only, treating verify endpoints as the system's core, intentionally open demonstration surface | Documented as a deliberate scope boundary, not an oversight, in `docs/security/threat_model.md` §10 | `tests/test_security.py` |
| 12 | Single-process in-process performance numbers do not establish production throughput/capacity | LOW (this review is explicit about it) | No real network stack, no multi-worker server, no realistic dataset size was measured | See `test_evidence.md` §8 — numbers are reported as observed local overhead only, with no extrapolation | `test_evidence.md` |

## Items explicitly NOT carried forward as residual risks

- The idempotency-cache concurrency race (found and fixed this stage — see
  `requirement_traceability.md` area 6).
- Any claim that "all tests pass" implies production readiness — this review's final
  classification in `production_readiness_report.md` explicitly does not conflate the
  two, per the P11 final rule.
