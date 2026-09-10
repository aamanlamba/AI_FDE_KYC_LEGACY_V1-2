# Architecture Overview — Stage P10

This is the final-state architecture after P0's forensic baseline and P1-P9's
successive capability builds. It documents what exists, module boundaries, provider
integration points, and what was deliberately *not* changed in this stage
("do not rewrite working components solely for aesthetic reasons").

## Module boundaries

| Boundary | Package(s) | Notes |
|---|---|---|
| API | `src/app.py` | FastAPI routes, exception handlers, auth/rate-limit/idempotency wiring, lifespan |
| Application orchestration | `src/service.py` | Composes every stage below into `verify_document`/`verify_case`. Deliberately kept as a single top-level module rather than moved into a new package (see "What was not changed" below) |
| Document Intelligence | `src/document_intelligence/` | Classification, quality assessment, provider interface + deterministic sidecar provider |
| Identity Resolution | `src/identity_resolution/` | Attribute normalization, matching, cross-document/application resolution |
| Validation | `src/evidence_validation/` | 10 computable-truth rule categories |
| Fraud Assessment | `src/fraud_signals/` | Signal derivation + forensics provider interface |
| Risk/Policy Decisioning | `src/decision_policy/` | `EvidenceBundle` → `RiskFactor`s → `RiskAssessment`, rule-based (not weighted-score) |
| HITL | `src/review/` | SQLite-backed review workflow, persistence provider interface |
| Observability | `src/observability/` | Trace context, spans, structured logging, metrics, decision lineage |
| Configuration | `src/policy.py`, `config/*.json` | Config-driven values + shared domain constants (see ADR-005) |
| Provider integrations | Distributed by domain + `src/providers/` | See table below |
| Security | `src/security/` | Cross-cutting: identifiers, redaction, auth, rate limits, idempotency |

`src/rules.py`, `src/parser.py`, `src/ocr.py`, `src/repository.py`, `src/models.py` are
the original P0 modules (parser/ocr/rules unchanged in logic since P0; repository
hardened in P8; models.py is the API-contract aggregator every stage added a field to).

## Dependency rules (verified, not assumed)

`tests/test_architecture.py::test_no_circular_imports_across_src_packages` builds the
actual import graph from the AST of every file in `src/` and asserts it is acyclic —
this is checked on every CI run, not just documented. The layering rule enforced
alongside it: `document_intelligence` and `fraud_signals` must never import from
`rules` (decisioning) again (see ADR-005 for why this was a violation worth fixing).

General direction of dependency (lower layers never depend on higher ones):
```
policy (leaf: config + shared domain constants)
  ^
  |
rules, document_intelligence, security, observability/context
  ^
  |
evidence_validation, identity_resolution
  ^
  |
fraud_signals, decision_policy
  ^
  |
review, models (API contract)
  ^
  |
service (orchestration)
  ^
  |
app (API)
```

## Provider inventory (P10 requirement 4)

Every provider interface in this repository, wherever it lives (co-located with its
owning domain, per this repository's established convention -- see "What was not
changed" below):

| Interface | Location | Default (only) implementation | Real-deployment implementation would... |
|---|---|---|---|
| `DocumentIntelligenceProvider` | `src/document_intelligence/provider.py` (P1) | `DeterministicSidecarProvider` | Call a real OCR/VLM service |
| `DocumentForensicsProvider` | `src/fraud_signals/provider.py` (P4) | `DeterministicMarkerForensicsProvider` | Perform real pixel-level image forensics |
| `ReviewSummaryProvider` | `src/review/summary.py` (P6) | `DeterministicReviewSummaryProvider` | Optionally call an LLM (with the guardrails in its docstring) |
| `Authorizer` | `src/security/auth.py` (P8) | `StaticWorkshopAuthorizer` | Integrate a real identity provider (OAuth2/OIDC/mTLS) |
| `ReviewRepository` | `src/review/store.py` (P10) | `ReviewStore` (SQLite) | Use Postgres/DynamoDB/etc. |
| `ExternalIdentityVerificationProvider` | `src/providers/external_identity.py` (P10, new) | `NullExternalIdentityProvider` | Call a government ID registry / credit bureau |
| `ExternalFraudSignalProvider` | `src/providers/external_fraud.py` (P10, new) | `NullExternalFraudSignalProvider` | Call a third-party fraud-scoring service |

The two new P10 interfaces are **not wired into `src/service.py`/`src/decision_policy/`**
— consuming a new evidence/signal source that could change a decision is a policy
change (P5's domain), not an architecture change, and is out of scope for this stage.
They exist as the documented seam a future stage would wire in, complete with the
shared `src/providers/resilience.py` retry/timeout helper a real network-backed
implementation would use.

## Configuration

| File | Loaded by | Contains |
|---|---|---|
| `config/baseline.json` | `src/policy.py` | `mandatory_fields`, `supported_document_types`, `min_field_completeness_for_approve` |
| `config/security.json` | `src/security/auth.py` | Workshop reviewer credentials (overridable via `REVIEWER_API_KEYS`) |

Environment variables (all optional, all have safe workshop defaults): `LOG_LEVEL`,
`REVIEW_DB_PATH`, `REVIEWER_API_KEYS`, `REVIEW_RATE_LIMIT_MAX`,
`REVIEW_RATE_LIMIT_WINDOW_SECONDS`. Full list with defaults:
`docs/operations/deployment.md`.

**Deliberately not externalized**: `src/rules.py`'s `REFERENCE_DATE` (frozen at
2026-09-09) — this is a reproducibility anchor for the workshop's golden-snapshot
tests, not an operational policy knob; making it configurable would let someone
silently break every regression test in `data/expected_baseline_outputs/` without
realizing why. Document-number regex patterns (`src/policy.py:PATTERNS`) — structural
facts about the synthetic document formats, not business thresholds.

## Concurrency (P10 requirement 11-12)

Business target: ~20,000 applications/day, 2-3 documents/application, ~15
verification requests/sec peak.

**What was actually measured** (`tests/test_architecture.py::test_concurrent_verify_requests_succeed_without_error_or_corruption`,
re-run as part of every CI test job): 60 concurrent `/v1/cases/{id}/verify` requests
across 15 threads via `TestClient`'s in-process ASGI transport all returned 200 with
the correct decision for their case — no exception, no cross-request state corruption.
An ad-hoc local run (not a committed, repeatable benchmark — see the caveat in that
test's docstring) observed ~420 req/sec on a single dev machine under this same
narrow setup.

**What this does and does not prove**: it proves the code has no discovered
concurrency defect (no shared-mutable-state bug) under a modest concurrent load. It
does **not** prove the service can sustain 15 req/sec, 423 req/sec, or any other
number in a real deployment — there is no real network stack, no multi-process/
multi-worker deployment, no real OCR/model latency, and no sustained-duration test
here. **P10 requirement 12 is explicit: do not claim load capability without
testing** — this document does not claim a capacity number; `docs/operations/slis_slos.md`
already separates measured numbers from proposed targets for exactly this reason.

**A real concurrency finding, fixed in this stage**: `src/observability/tracing.py`'s
per-trace span-stack dict was never pruned after a trace's root span completed --
an unbounded per-request memory leak under sustained traffic (every request gets a
unique trace_id by default). Found during this stage's concurrency review, fixed by
deleting the entry once nothing is left to nest under, and guarded with a lock (see
`git log`/this stage's diff for `src/observability/tracing.py`).

**Structural concurrency properties, already true**: `src/review/store.py`'s SQLite
access is serialized behind one lock per `ReviewStore` instance (correct, but a
throughput ceiling under heavy review-mutation load specifically — the stateless
verify endpoints, the overwhelming majority of expected traffic, have no such
serialization point). `src/security/limits.py`'s `RateLimiter` and
`src/security/idempotency.py`'s `IdempotencyCache` are each independently locked.

## What was deliberately NOT changed in this stage

Per this stage's own top-line instruction. Each of these was considered and rejected:

1. **Moving `src/service.py` into a new `src/orchestration/` package.** It already is
   the application-orchestration layer, clearly named and singularly responsible;
   moving it would touch every importer (`app.py`, every test, the eval harness,
   `scripts/`) for zero functional benefit.
2. **Re-homing existing provider interfaces into `src/providers/`.** P1-P8 established
   the convention of co-locating a provider interface with its owning domain
   (`DocumentIntelligenceProvider` in `document_intelligence/`, etc.). Moving them
   would fragment related code across two locations for organizational aesthetics.
   `src/providers/` holds only the genuinely new P10 interfaces that had no existing
   domain home.
3. **Renaming `ReviewStore` to `SqliteReviewRepository`.** It now formally implements
   `ReviewRepository`; renaming the concrete class would touch `app.py`,
   `review/workflow.py`, and every test that references it by name, for a purely
   cosmetic gain.
4. **Consolidating `eval/pipeline.py`'s duplication of `service.py`'s composition.**
   Documented and accepted in P7 for a specific reason (the eval harness must not
   require new `data/` fixtures); revisited in this stage and the reasoning still
   holds. Unifying them would require a new abstraction whose only consumer would be
   the eval harness -- not worth the added indirection.
5. **A multi-stage Docker build.** The current dependency set is lightweight; a
   multi-stage build would add complexity without a proportionate image-size benefit
   for this specific app.

## ADRs

See `docs/architecture/adr/` for the record of the most consequential decisions made
across P0-P10, including the ones referenced above.
