# Data Dictionary

## Application (`data/applications/<case>.json`)
| Field | Type | Meaning |
|---|---|---|
| case_id | string | Synthetic applicant case identifier |
| submitted_name | string | Name supplied in onboarding form |
| submitted_dob | YYYY-MM-DD | Claimed date of birth |
| submitted_address | string | Claimed address |
| document_ids | array[string] | Evidence documents associated with the case |
| scenario | string | Training scenario label |

## Ground truth (`data/ground_truth/<document_id>.json`)
| Field | Type | Meaning |
|---|---|---|
| document_id | string | Synthetic document identifier |
| case_id | string | Owning synthetic case |
| document_type | enum | passport / national_id / driving_licence |
| full_name | string | Canonical value rendered on document |
| date_of_birth | YYYY-MM-DD | Canonical DOB |
| document_number | string | Synthetic document number |
| issue_date | YYYY-MM-DD | Issue date |
| expiry_date | YYYY-MM-DD | Expiry date |
| address | string/null | Address where relevant |
| nationality | string/null | Synthetic nationality label |
| scenario_flags | array[string] | clean/noisy/rotated/expired/name_variation/ocr_error/suspected_tampering |

## Baseline response
| Field | Meaning |
|---|---|
| decision | APPROVE / REVIEW / REJECT |
| reason_codes | Deterministic baseline reason codes |
| parsed_fields | Values extracted from OCR sidecar (legacy flat contract, unchanged) |
| completeness | Fraction of mandatory fields present |
| warnings | Parser/validation warnings |
| source | Indicates deterministic sidecar OCR |
| evidence | Structured `DocumentEvidence` from the Document Intelligence layer (additive; see below) |
| identity_resolution | (Case-level only) Structured `IdentityResolutionResult` from cross-document identity resolution (added in stage P2; see below) |
| validation | Structured `DocumentValidationReport` (per document) / `CaseValidationReport` (case-level) from the evidence validation subsystem (added in stage P3; see below) |
| fraud_signals / fraud_assessment | `DocumentFraudSignals` (per document) / `FraudAssessment` (case-level) from the fraud-signal subsystem (added in stage P4; see below) |
| risk_assessment | (Case-level only) `RiskAssessment` — the explicit basis for `decision`, added in stage P5; see below |

**Stage P5 changed how `decision`/`reason_codes` are computed at the case level** (not
just an additive field): `CaseResult.decision` is now `risk_assessment.policy_outcome`,
not "the worst individual document decision." `DocumentResult.decision` (per document)
is unchanged since P0 — it remains one input among several to the case-level policy.
`CaseResult.reason_codes` is now the union of the legacy per-document reason codes
(preserved for operational compatibility — e.g. `DOCUMENT_EXPIRED`, `SUSPECTED_TAMPERING`
still appear when applicable) and `risk_assessment.reason_codes` (new, policy-level
codes such as `HARD_STOP:document_decision`, `REVIEW:identity_conflict`).

## Document evidence (`evidence`, added in stage P1)

Additive, schema-validated structured evidence produced by the Document Intelligence
provider interface (`src/document_intelligence/`). This does not replace `parsed_fields`
and does not feed the current decision rules (`src/rules.py`) — it is evidence
enrichment only; identity resolution and risk decisioning remain out of scope until a
later stage.

| Field | Meaning |
|---|---|
| document_id | Synthetic document identifier |
| document_type | Classifier output: `passport` / `national_id` / `driving_licence` / `unknown` |
| fields | Map of field name → `EvidenceField` (see below) for the 7 canonical fields relevant to the classified type |
| quality | `normal` / `degraded` / `rotated` / `incomplete_unreadable` |
| extraction_warnings | Document-level warnings (unparsed lines, quality signals, classification anomalies) |
| provider | Name of the provider that produced this evidence (`deterministic_sidecar_ocr` today) |
| evidence_reference | Path to the underlying evidence artifact (the sidecar OCR file) |

### `EvidenceField`
| Field | Meaning |
|---|---|
| value | Raw extracted value, or `null` if the field was not found (never fabricated) |
| normalized_value | Whitespace/case-normalized value; `null` if missing or fails format validation. Never "corrects" OCR content. |
| confidence | Deterministic heuristic in `[0, 1]` derived from document quality and per-field format validation — not a calibrated probability |
| source | Provider name |
| provenance | Locator back to the evidence artifact and field (e.g. `data/sidecar_ocr/<doc>.txt#field=<name>`) |
| warnings | e.g. `FIELD_NOT_FOUND`, `FIELD_FORMAT_INVALID` |

## Identity resolution (`identity_resolution`, added in stage P2)

Additive, schema-validated cross-document identity comparison
(`src/identity_resolution/`). Explicitly answers whether the submitted application and
every document's extracted evidence describe a consistent claimed identity for
`full_name`, `date_of_birth`, and `address` (where present). `document_number` is
deliberately **not** compared cross-document — different document types legitimately
carry different identifiers for the same person. This is evidence-strength reporting
only: it does not change `decision` in this stage (that remains the unchanged
worst-of-documents policy in `src/rules.py`/`src/service.py`) and is not itself a risk
policy.

| Field | Meaning |
|---|---|
| case_id | Synthetic case identifier |
| overall_status | Worst status across all attributes: `EXACT` / `NORMALIZED_MATCH` / `FUZZY_MATCH` / `CONFLICT` / `INSUFFICIENT_EVIDENCE` |
| confidence | `[0,1]` evidence-strength heuristic. Forced to `0.0` if `overall_status` is `CONFLICT` — a confirmed contradiction is never averaged away by other clean attributes |
| attribute_comparisons | Per-attribute (`full_name`, `date_of_birth`, `address`) breakdown — sources, pairwise comparisons, status, reason codes |
| conflicts | Human-readable descriptions of every pairwise `CONFLICT` found |
| supporting_documents | Document IDs that contributed evidence |
| reason_codes | e.g. `IDENTITY_CONFLICT`, `FULL_NAME_FUZZY_MATCH`, `ADDRESS_INSUFFICIENT_EVIDENCE` |

### Match status semantics
| Status | Meaning |
|---|---|
| `EXACT` | Raw values are character-identical |
| `NORMALIZED_MATCH` | Differ only by whitespace/punctuation/case, initials (`JOHN A SMITH` vs `JOHN ANDREW SMITH`), or token order (`SMITH JOHN` vs `JOHN SMITH`) — deterministic, explainable rules, not similarity scoring |
| `FUZZY_MATCH` | Below normalization rules but above a calibrated similarity threshold (e.g. OCR-corrupted spelling). **Never treated as proof of identity by itself** — it is reported, not upgraded |
| `CONFLICT` | Materially different values (name similarity below threshold, or any DOB mismatch — dates are exact-or-contradiction, never fuzzy) |
| `INSUFFICIENT_EVIDENCE` | Fewer than two sources available for that attribute (e.g. an attribute only the application supplied, with no document corroborating it) |

## Evidence validation (`validation`, added in stage P3)

Additive, schema-validated, deterministic validation (`src/evidence_validation/`),
separated out of the legacy `src/rules.py` rule function into individually auditable
rules. This is **computable-truth checking only** — it does not decide
APPROVE/REVIEW/REJECT (that remains `src/rules.py`'s unchanged decision policy, pending a
later risk-policy stage) and it does not assess authenticity/tampering (that also
remains in `src/rules.py`, unchanged, via its literal tamper-marker check).

| Field (`DocumentValidationReport`) | Meaning |
|---|---|
| document_id | Document identifier |
| reference_date | The ISO date actually used for temporal/expiry checks in this run (see below) |
| results | List of `ValidationResult`, one or more per category |

| Field (`CaseValidationReport`) | Meaning |
|---|---|
| case_id | Case identifier |
| reference_date | Same as above, case-wide |
| document_reports | Every document's `DocumentValidationReport` (not recomputed — reused from each `DocumentResult.validation`) |
| case_level_results | Cross-document structural checks (currently: no duplicate document type within a case) |

### `ValidationResult`
| Field | Meaning |
|---|---|
| rule_id | e.g. `EXPIRY-NOT-PAST`, `MANDATORY-FULL_NAME`, `ISSUEDATE-BEFORE-EXPIRY` |
| rule_version | Rule-set version (`1.0.0`) — bump when a rule's logic changes, for audit traceability |
| category | One of the 10 categories below |
| status | `PASS` / `FAIL` / `UNKNOWN` / `NOT_APPLICABLE` / `NOT_IMPLEMENTED` |
| severity | `INFO` / `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` |
| reason_code | Machine-readable outcome code |
| explanation | Human-readable, evidence-specific explanation |
| evidence_references | Provenance locator(s) this finding traces back to (never empty) |

### Validation categories
`schema_validation`, `mandatory_field_validation`, `document_number_format_validation`,
`date_validation`, `temporal_validation`, `expiry_validation`, `issue_date_consistency`,
`cross_field_validation` (date_of_birth precedes issue_date), `document_type_validation`,
`cross_document_consistency_validation` (no duplicate document type in a case),
`authenticity_checksum_validation` (always `NOT_IMPLEMENTED` — see below).

### Status semantics
| Status | Meaning |
|---|---|
| `PASS` | The rule's condition holds |
| `FAIL` | The rule's condition does not hold — a genuine, computable finding |
| `UNKNOWN` | The rule could apply, but the evidence is too poor (`quality=incomplete_unreadable`) to confidently confirm or deny it — used instead of guessing `FAIL` |
| `NOT_APPLICABLE` | The rule's precondition isn't met (a dependency field is missing or malformed elsewhere — see `DATE-FORMAT-*`) — extraction failure is never reported as if it were a validation `PASS` or `FAIL` |
| `NOT_IMPLEMENTED` | The rule is meaningful in principle but this system has no capability to evaluate it (checksum/signature verification on synthetic evidence). A disclosed capability boundary, never a fabricated `PASS` |

### Reference date injection
Every check that needs "now" (temporal, expiry) defaults to `src/rules.py`'s frozen
`REFERENCE_DATE` (2026-09-09, for reproducible workshop results) but accepts an
injected `reference_date` parameter — used by tests to exercise boundary dates without
touching the frozen default.

### Config-driven policy (stage P3)
`src/policy.py` loads `mandatory_fields`, `supported_document_types` and
`min_field_completeness_for_approve` from `config/baseline.json` when present (falling
back to the historical hard-coded values otherwise), and both `src/rules.py` and
`src/evidence_validation/` consume these values — closing the gap where
`config/baseline.json` previously had no effect on running behaviour.

## Fraud signals (`fraud_signals` / `fraud_assessment`, added in stage P4)

Additive, schema-validated fraud *evidence* (`src/fraud_signals/`), explicitly
separated from decision policy. This layer reports labeled `FraudSignal` findings; it
does not decide APPROVE/REVIEW/REJECT (unchanged in `src/rules.py`, pending a later
risk-policy stage) and it never independently declares a document fraudulent — no
implementation in this repository calls an LLM, or any opaque judgment source, to reach
a fraud conclusion. Every signal is grounded in a real, executable, deterministic check.

### `FraudSignal`
| Field | Meaning |
|---|---|
| signal_id | Traceable identifier, e.g. `CASE-006-PASSPORT:TAMPER_MARKER_DETECTED` |
| category | `tamper_marker` / `field_inconsistency` / `temporal_anomaly` / `extraction_inconsistency` / `identity_conflict` / `document_duplication` / `sidecar_metadata_anomaly` (reserved, currently unused) |
| severity | `INFO` / `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` (same scale as `evidence_validation.Severity`) |
| confidence | `[0,1]` or `null`. `null` for binary/deterministic findings (a marker match, a rule FAIL) where a probability would be meaningless; numeric only where genuinely derived from a similarity score (e.g. identity-conflict signals: `confidence = 1 - name_similarity`) |
| source | Accurately labeled origin, e.g. `deterministic_marker_forensics:sidecar_text_substring_match`, `evidence_validation:ISSUEDATE-BEFORE-EXPIRY`, `identity_resolution:full_name` — never implies a capability this system doesn't have |
| supporting_evidence | Provenance reference(s) this signal traces back to |
| explanation | Human-readable, evidence-specific explanation |

### `DocumentFraudSignals` / `FraudAssessment`
| Field | Meaning |
|---|---|
| document_signals | Per-document signal lists (tamper marker, temporal anomaly, extraction inconsistency — reused from each `DocumentResult.fraud_signals`, not recomputed) |
| case_level_signals | Cross-document signals: `identity_conflict` (from `identity_resolution` `CONFLICT` pairwise comparisons) and `document_duplication` (from `evidence_validation`'s `CROSSDOC-NO-DUPLICATE-TYPE`) |
| status | `NO_SIGNALS_DETECTED` / `FRAUD_SIGNAL_PRESENT` / `FRAUD_PROVEN` (see below) |
| signal_count | Total signals across documents and case-level |
| highest_severity | The most severe signal's severity, or `null` if none |
| reason_codes | e.g. `FRAUD_SIGNAL:tamper_marker`, `FRAUD_SIGNAL:identity_conflict`, or `NO_FRAUD_SIGNALS_DETECTED` |

### `FRAUD_SIGNAL_PRESENT` vs `FRAUD_PROVEN`
`FRAUD_PROVEN` is a reserved status: **no code path in this repository can produce it.**
Proving fraud would require evidence this offline, deterministic signal set cannot
generate — corroborated investigation, cryptographic verification, or a confirmed
forensic match. Every real and adversarially-constructed synthetic scenario tested
(`tests/test_fraud_signals.py`) caps at `FRAUD_SIGNAL_PRESENT`, including a
maximal case combining a tamper marker, a temporal impossibility, an identity
conflict, and document duplication simultaneously.

### What counts as a fraud-relevant signal (and what deliberately doesn't)
- **Temporal anomaly**: only genuinely impossible relationships — issued in the future,
  issued after/on its own expiry, or issued before the holder's date of birth. Plain
  expiry (a document simply being out of date) is deliberately excluded: it's a
  mundane lifecycle event, not an anomaly.
- **False-positive resistance**: `OCR_QUALITY: DEGRADED` and `CAPTURE_ORIENTATION:
  90_DEGREES` markers never produce a fraud signal on their own — those are ordinary
  capture-condition markers already handled by the Document Intelligence quality layer
  (P1), not fraud indicators.
- Only actual `FAIL` results from `evidence_validation` become signals — `NOT_APPLICABLE`
  or `UNKNOWN` (missing or unreadable evidence) never fabricates a signal.

### Document forensics provider interface
`src/fraud_signals/provider.py` defines `DocumentForensicsProvider`, an interface a
future real forensics provider (image manipulation detection, metadata/EXIF analysis,
cryptographic signature checks) would implement. Its only current implementation,
`DeterministicMarkerForensicsProvider`, performs a literal text-marker scan against the
deterministic OCR sidecar — **not** pixel-level image forensics, which this repository
cannot perform (its extraction layer never reads image pixels; confirmed by `grep -rn
"PIL\|Image\|\.png" src/` returning no matches outside test/ops tooling). The marker
registry (`src/fraud_signals/registry.py`) currently contains exactly one entry — the
synthetic `ALTERED_TEXT_REGION_DETECTED` tamper fixture — reflecting only what is
actually present in this training dataset ("where present"), not a fabricated
capability.

## Decision policy (`risk_assessment`, added in stage P5)

`src/decision_policy/` is the explicit decisioning layer. It aggregates every prior
stage's evidence (Document Intelligence, Identity Resolution, Evidence Validation,
Fraud Signals) into an internal `EvidenceBundle`, derives a list of `RiskFactor`
objects, and applies a deterministic, rule-based policy — **not** an opaque weighted
score. `CaseResult.decision` **is** `risk_assessment.policy_outcome`.

### `RiskFactor`
| Field | Meaning |
|---|---|
| factor_id | Traceable identifier, e.g. `CASE-005:full_name:CONFLICT` |
| category | `document_decision` / `identity_conflict` / `identity_uncertainty` / `fraud_signal` / `validation_failure` / `evidence_quality` |
| severity | `INFO` / `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` (same scale used throughout P3/P4) |
| triggers_hard_stop | The only thing the policy engine reads to decide REJECT vs. REVIEW — set explicitly where each factor is derived, never inferred implicitly at decision time |
| description, source, evidence_references | Human-readable explanation and traceability back to the originating evidence layer |

### `RiskAssessment`
| Field | Meaning |
|---|---|
| case_id | Case identifier |
| policy_version | e.g. `1.0.0` — bump whenever the rules in `src/decision_policy/engine.py` change. Decisions are reproducible from retained evidence (every layer's output is already retained on `CaseResult`) plus this version. |
| risk_factors | Every factor considered — the full, inspectable basis for the outcome |
| evidence_strength | `[0,1]` descriptive heuristic, **not a calibrated probability**. Mean of two separately-computed components — extraction-layer field confidence, and identity-resolution match strength — so extraction confidence is never conflated with identity risk (requirement 3). Does not affect `policy_outcome`. |
| uncertainty | `[0,1]` descriptive heuristic, **not a calibrated probability**. `min(1.0, 0.2 × count)` of missing/unknown/ambiguous evidence signals (unreadable documents, `UNKNOWN` validation results, `INSUFFICIENT_EVIDENCE` identity attributes). Does not affect `policy_outcome`. |
| validation_failure_count, identity_conflict_count, fraud_signal_count | Convenience counts by risk-factor category |
| hard_stop_triggered | `true` iff any risk factor has `triggers_hard_stop=true` |
| policy_outcome | `APPROVE` / `REVIEW` / `REJECT` — authoritative; this becomes `CaseResult.decision` |
| reason_codes | Per-factor codes, e.g. `HARD_STOP:document_decision`, `REVIEW:identity_conflict`, or `POLICY_APPROVED_NO_RISK_FACTORS` when there are no factors at all |
| explanation | Analyst-facing narrative: factor counts by category, and (for REJECT) which specific hard-stop factors triggered it |

### The policy rule, in full
```
hard_stop = any(factor.triggers_hard_stop for factor in risk_factors)
if hard_stop:            return REJECT
elif risk_factors:       return REVIEW
else:                    return APPROVE
```
Hard-stop conditions (defined where each factor is derived, `src/decision_policy/factors.py`):
- Any document independently REJECTed by `src/rules.py` (expiry, tamper marker, format) — unchanged since P0.
- A CRITICAL-severity fraud signal (currently: the tamper-marker signal).
- A **date_of_birth** identity conflict specifically — dates are exact-or-contradiction
  (never fuzzy, see `src/identity_resolution/matching.py`), making this the least
  ambiguous identity hard-stop available.
- A CRITICAL-severity validation failure (reserved; no current rule reaches CRITICAL).

Everything else that produces a risk factor (a document-level REVIEW, a fuzzy or
insufficient-evidence identity attribute, a non-DOB identity conflict, a non-CRITICAL
fraud signal, a validation FAIL below CRITICAL, an unreadable document, an UNKNOWN
validation result) is review-level, not a hard stop — deliberately, since none of these
alone is proof of a genuine problem (see requirement 7 in `identity_resolution`'s design:
fuzzy similarity is never treated as proof of identity, and the same principle applies
here to weaker signals generally).

### Why a rule list instead of a weighted score
A single numerical risk score that sums weighted contributions was deliberately not
used for the decision itself: with heterogeneous evidence (a document rejection, an
identity conflict, a fraud signal, a validation failure) any fixed weighting is an
implicit policy choice that is hard to justify, hard to test exhaustively, and easy to
game by a case with many small "safe" signals diluting one serious one. The explicit
hard-stop/review split makes every decision traceable to specific, named factors
(`tests/test_decision_policy.py` tests the rule list directly, not a threshold on a
score). `evidence_strength`/`uncertainty` still provide the descriptive numeric summaries
`RiskAssessment` asks for, but only as analyst context — never as the decision input.

## Human-in-the-loop review (`src/review/`, added in stage P6)

Unlike every prior stage's evidence layers, `ReviewCase` is **not** an additive field on
`CaseResult` — it is a separate, durable resource behind new API paths (existing
endpoints and response shapes are completely unaffected; see "New endpoints" below).
Only a case whose `decision` is `REVIEW` may open an ordinary review — any other
decision is rejected (`409`), since no alternate policy route into this workflow is
defined in this repository.

### Persistence
SQLite (`src/review/store.py`, `ReviewStore`) — a locally-runnable, dependency-free
(stdlib `sqlite3`) durable store. Default file path is `var/review_store.sqlite3`
(gitignored; created on first use), overridable via the `REVIEW_DB_PATH` environment
variable. `review_cases.status` is the only mutable column; every change to it is
preceded by an insert-only row in `review_audit_log`, so the full transition history is
always reconstructable.

### `ReviewCase`
| Field | Meaning |
|---|---|
| review_id | e.g. `RVW-CASE-005-683d3c53` |
| case_id | The case this review is for |
| trigger | The category of the highest-severity `RiskFactor` that led to `REVIEW` (e.g. `identity_conflict`) |
| priority | `LOW` / `MEDIUM` / `HIGH`, derived from the highest severity among the case's risk factors |
| evidence_summary | Concise structured snapshot: document count/types, key fields (`full_name`, `date_of_birth`) per document |
| discrepancies | From `identity_resolution`: recorded conflicts, plus fuzzy-match attributes |
| failed_validations | Every `FAIL`-status result from `validation` (document- and case-level) |
| fraud_signals | Every signal from `fraud_assessment`, described |
| reason_codes | Copied from the triggering `CaseResult.reason_codes` |
| status | `OPEN` / `IN_REVIEW` / `RESOLVED` / `ESCALATED` |
| created_at | Real wall-clock ISO8601 timestamp (this is genuinely operational state, unlike the deterministic evidence-computation layers, so it is intentionally not tied to the frozen `REFERENCE_DATE`) |
| policy_version | `risk_assessment.policy_version` at the moment the review was opened |
| reviewer_summary | Deterministic, evidence-grounded narrative (see below) |

**Immutability**: every field above is captured once, when the review is opened, and
never mutated afterward — not even by a later analyst correction. This is deliberate:
an analyst's correction is recorded only in that transition's `ReviewAuditEntry.correction`,
layered on top of the original snapshot, never overwriting it.

### State machine
```
OPEN -> IN_REVIEW -> RESOLVED
                   -> ESCALATED
```
`RESOLVED`/`ESCALATED` are terminal. Any pair not listed above — including a state
transitioning to itself (e.g. re-submitting the same "start review" action) — is
rejected with `409` and does not create a new audit entry or change `status`.

### `ReviewAuditEntry` (append-only; `review_audit_log` table)
| Field | Meaning |
|---|---|
| analyst_action | Free-text label of what the analyst did |
| correction | Optional: a specific data correction the analyst notes (layered evidence, never a rewrite — see above) |
| rationale | Required: why this action was taken |
| timestamp | Real wall-clock ISO8601 |
| prior_state, new_state | Captured automatically by the transition, not supplied by the caller |

### Reviewer summary — grounding and the LLM guardrail
`src/review/summary.py` defines `ReviewSummaryProvider`, an interface (mirroring
`DocumentIntelligenceProvider`/`DocumentForensicsProvider`) whose only implementation in
this repository, `DeterministicReviewSummaryProvider`, composes a narrative entirely
from already-computed, already-retained evidence (`risk_assessment.explanation`,
`identity_resolution.conflicts`, fraud signals) — deterministic, offline, and never
inventing a claim the underlying `CaseResult` doesn't support. **No LLM is called
anywhere in this repository.** If an LLM-generated summary capability were ever added,
the interface requires any such implementation to: sit behind this interface; keep the
deterministic offline fallback available regardless; ground every statement in the
supplied evidence; and never invent facts.

### New endpoints (additive; existing endpoints unchanged)

**As of stage P8, every endpoint below requires an `X-API-Key` header** with a
credential holding the `reviewer` role (workshop default: `workshop-reviewer-key`, see
`config/security.json`; override via the `REVIEWER_API_KEYS` environment variable).
Missing/invalid credential → `401`; valid credential without the role → `403`. See
`docs/security/threat_model.md` §10 for why (`/v1/documents/verify` and
`/v1/cases/{id}/verify` remain unauthenticated — a documented, deliberate scope
boundary, not an oversight).

| Method & path | Purpose |
|---|---|
| `POST /v1/cases/{case_id}/reviews` | Open a review (`201`), or return the existing open one if already open (`201`, idempotent-by-case); `409` if `decision != REVIEW` |
| `GET /v1/reviews` | List reviews, optional `?status=` filter |
| `GET /v1/reviews/{review_id}` | Get one review (`404` if unknown) |
| `GET /v1/reviews/{review_id}/history` | The full, ordered audit trail |
| `POST /v1/reviews/{review_id}/transitions` | Apply an analyst action (`409` on an invalid transition; `429` if the rate limit is exceeded — 20 transitions/60s per credential) |

Example:
```bash
curl -X POST http://127.0.0.1:8000/v1/cases/CASE-005/reviews \
  -H "X-API-Key: workshop-reviewer-key"
```

## Evaluation harness (`eval/`, added in stage P7)

Independent of `tests/` (ordinary regression/unit testing, unaffected by and unaware of
this package — P7 requirement 1). Answers "did the transformation actually improve
system quality without introducing unsafe regressions?" by running a curated case set
through the real pipeline (`src.service.verify_case` for repository-backed cases;
`eval/pipeline.py`'s direct composition, mirroring `verify_case`, for synthetic ones —
neither modifies `src/`) and computing metrics + release gates from the results.

**Run it**: `python scripts/run_evaluation.py` — the single command (P7 requirement
11). Prints a summary, writes a machine-readable report to `var/eval/report.json`
(gitignored; P7 requirement 9), and **exits non-zero if any release gate fails** —
suitable for CI.

### Case categories (`eval/cases.py`)
All 10 required categories (`golden`, `noisy`, `rotated`, `ocr_corrupted`, `expired`,
`identity_variation`, `fraud_tampering`, `missing_evidence`, `contradictory_evidence`,
`adversarial_malformed`) are represented. Categories the real 6-case/13-document
dataset can naturally exercise wrap the corresponding repository `case_id` (full
fidelity — goes through `src.ocr`/`src.parser`/`src.rules` too). Categories it cannot
(`missing_evidence`, `contradictory_evidence`, `adversarial_malformed`) are small,
explicitly-synthetic in-memory cases, never added to `data/` — `scripts/sanity_check.py`'s
exact case/document counts are untouched by this stage.

### Sample-size honesty (P7 requirements 5, 6)
Every rate in the report carries its raw `(numerator, denominator)` and a
`sample_size_warning` flag (true below n=30). The report's top-level
`sample_size_disclaimer` states plainly that this is a small, hand-curated,
deliberately adversarial-weighted case set — not a statistically representative
sample. **FAR/FRR semantics are stated explicitly in the report itself
(`decisioning.far_frr_semantics`) before any number is shown**: they measure agreement
with each case's *scenario-design label* (what it was built to represent) on this small
set, not a calibrated error rate against any real population — this repository's
decision policy is a deterministic rule engine, not a statistical/biometric classifier.

### Metrics computed (`eval/metrics.py`)
| Component | Metrics |
|---|---|
| Document Intelligence | exact match, normalized match, missing-field rate, field-presence precision/recall/F1, per-field breakdown |
| Identity Resolution | match-status accuracy (vs. each case's labeled expected `MatchStatus`), conflict-detection accuracy (vs. each case's labeled `should_have_identity_conflict`) |
| Decisioning | decision accuracy (vs. labeled expected decision), false acceptance, false rejection, review/referral rate |
| Operations | straight-through-processing rate (real 6-case dataset), latency (30 repeated in-process `verify_case` calls — same "not a load test" caveat as `docs/assessment/behavioural_baseline.md`), error rate (unexpected-exception count vs. cases that explicitly expect one) |

### Metamorphic and adversarial checks (`eval/metamorphic.py`, requirements 7-8)
Run against a synthetic clean baseline case (`APPROVE`), each check compares it to one
transformed variant:
- **Invariance** (harmless — decision must stay the same): case (upper/lower),
  spacing, punctuation, document ordering.
- **Adversarial sensitivity** (genuine — decision must change): DOB corruption, tamper
  marker injection, swapping in a genuinely different person's name. This guards
  against a harness that would trivially pass invariance checks by ignoring its input
  entirely.

### Release gates (`eval/gates.py`, requirement 10)
Six gates, each individually justified and calibrated to what the current, correct
system actually satisfies (verified by running the suite, not assumed): zero
unexpected exceptions; 100% metamorphic invariance; 100% adversarial sensitivity; zero
false acceptance on labeled fraud/tamper/contradiction cases; ≥90% decision accuracy on
the labeled set; ≥95% document field exact-match on the real dataset. `tests/test_eval_harness.py`
proves the gate mechanism itself is sound (each gate is shown to actually fail against
a deliberately-broken synthetic report, not just always pass).

## Security & privacy hardening (`src/security/`, added in stage P8)

Full threat model: `docs/security/threat_model.md`. Full data-flow/retention
inventory: `docs/security/privacy_data_flow.md`. Summary of the new package:

| Module | Purpose |
|---|---|
| `identifiers.py` | Allowlist identifier validation (replaces the P0 denylist in `src/repository.py:safe_id`) |
| `redaction.py` | `sanitize_for_display` (strips control chars/caps length before document content reaches a narrative string), `redact_partial`/`mask_tail` (partial masking for lower-trust display contexts) |
| `auth.py` | `Authorizer` interface + `StaticWorkshopAuthorizer` (deterministic, config/env-driven); gates every `/v1/reviews*` endpoint |
| `limits.py` | `RateLimiter` (in-memory, fixed-window); gates `POST /v1/reviews/{id}/transitions` |
| `logging_utils.py` | `log_operational_event` — an allowlist-of-field-**names** logging helper |
| `errors.py` | `AuthenticationError` (401), `AuthorizationError` (403), `RateLimitExceededError` (429) |

Also in this stage: a centralized `Exception` handler in `src/app.py` returns a
generic, sanitized `500` to callers while logging full detail server-side with the
request's correlation ID; `model_config = ConfigDict(extra='forbid')` on both
user-facing request models (`VerifyDocumentRequest`, `ReviewTransitionRequest`); a
1 MB file-read bound in `src/repository.py`; and `ReviewStore.purge_review()`, the
retention/deletion primitive documented in `docs/security/privacy_data_flow.md` §4.

## Observability & decision lineage (`src/observability/`, added in stage P9)

One trace/correlation context is bound per HTTP request (`src/app.py`'s correlation
middleware) and propagated via `contextvars` — not a function parameter — across every
component: API → `document_intelligence` → `evidence_validation` → `identity_resolution`
→ `fraud_signals` → `decision_policy` → `review`. Every pipeline stage in
`src/service.py`/`src/review/workflow.py` opens a span (`src/observability/tracing.py`)
that nests correctly under the request's root span. Full local diagnostic procedures
using this: `docs/operations/runbook.md`. SLI definitions and proposed (not measured)
SLOs: `docs/operations/slis_slos.md`.

| Module | Purpose |
|---|---|
| `context.py` | `TraceContext` (trace_id, correlation_id) propagated via `contextvars`; `bind_trace_context()`, `get_current_trace_context()` |
| `tracing.py` | `Span`/`SpanExporter` abstraction using OpenTelemetry's own core concepts (trace_id, span_id, parent_span_id) without the dependency; `LoggingSpanExporter` (default) emits one structured log line per span; `InMemorySpanExporter` for tests |
| `logging_config.py` | JSON structured log formatter; injects the current trace context into every log line automatically |
| `metrics.py` | Dependency-free `Counter`/`Histogram` registry rendered in Prometheus-text-exposition format at `GET /metrics` |
| `versions.py` | `component_versions()` — consolidated version/identifier string per component |
| `lineage.py` | `DecisionLineage` — the object an auditor reads to reconstruct a decision without source access |

### `GET /metrics`
Prometheus-text-compatible (unauthenticated, like `/health/*` — a metric value can
never itself be a raw identity attribute, so this is safe by construction). Metrics:
`kyc_request_count`, `kyc_error_count`, `kyc_request_latency_ms`,
`kyc_extraction_failures_total`, `kyc_validation_failures_total`,
`kyc_identity_conflicts_total`, `kyc_fraud_referrals_total`, `kyc_decisions_total`,
`kyc_manual_review_created_total`, `kyc_document_types_total`,
`kyc_provider_failures_total`.

### `GET /health/ready` (enhanced)
Now returns a `checks` object verifying meaningful dependencies, not just "the process
is up": `dataset` (readable, non-empty), `review_store` (SQLite connection responds),
`auth_config` (at least one reviewer credential configured). `status` is `"degraded"`
(still HTTP `200`) if any check is non-`"ok"`.

### `CaseResult.decision_lineage`
Additive field. Not a recomputation — every piece is already retained elsewhere on
`CaseResult` (`risk_assessment`, `validation`, `fraud_assessment`, `identity_resolution`);
this adds the two things nothing else captured: which trace produced this decision, and
which exact version of every component did.

| Field | Meaning |
|---|---|
| trace_id | Ties this decision to its full span trace (see the runbook's Diagnostic 3) |
| policy_version | Same value as `risk_assessment.policy_version` |
| component_versions | `document_intelligence_provider`, `fraud_forensics_provider`, `identity_resolution`, `evidence_validation`, `decision_policy` — every version string needed to know exactly which logic ran |
| risk_factor_summary | One line per risk factor, human-readable |
| evidence_reference_count | Total evidence references across all risk factors — a quick completeness signal (zero would be suspicious for a non-`APPROVE` decision) |

**Note on reproducibility testing**: `decision_lineage.trace_id` is intentionally
unique per call (it identifies a specific traced operation, not a property of the
evidence) — `tests/test_release_integrity.py` and `scripts/sanity_check.py` bind a
fixed `trace_id="baseline"` via `bind_trace_context()` before comparing against the
committed golden snapshots, so those remain true byte-for-byte regression checks
rather than failing on an intentionally-volatile field.
