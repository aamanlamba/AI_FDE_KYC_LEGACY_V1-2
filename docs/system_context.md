# Repo 1.0 System Context

```text
Synthetic application + identity document image
                |
                v
        FastAPI endpoint
                |
                v
       Sidecar OCR loader
      (offline deterministic)
                |
                +----------------------------------------+
                v                                         v
       Regex / line parser                  Document Intelligence provider
                |                            (src/document_intelligence/)
                v                            classification + quality assessment
     Per-document validation                 + schema-validated DocumentEvidence
     rules (src/rules.py,                                |
     unchanged since P0 --                  +-------------+-------------+
     format/expiry/tamper,                  v                           v
     still drives each              Evidence Validation engine   Identity Resolution
     document's own decision)       (src/evidence_validation/)   (src/identity_resolution/)
                |                   10 computable-truth rule     cross-document attribute
                |                   categories, PASS/FAIL/       matching (full_name/DOB/
                |                   UNKNOWN/NOT_APPLICABLE/      address vs submitted
                |                   NOT_IMPLEMENTED per rule     application)
                |                              |                           |
                |                              v                           v
                |                   Fraud Signal engine (src/fraud_signals/)
                |                   tamper marker (labeled fixture-source) +
                |                   temporal impossibilities + identity conflicts +
                |                   document duplication -> FraudSignal evidence,
                |                   never a verdict
                |                              |
                +------------------------------+------------------------------+
                                                v
                            Decision Policy engine (src/decision_policy/)
                            EvidenceBundle -> explicit, inspectable RiskFactors
                            (hard-stop vs. review, never an opaque weighted score)
                            -> RiskAssessment (policy_outcome, reason_codes,
                               explanation, policy_version)
                                                |
                                                v
                     CaseResult.decision = risk_assessment.policy_outcome
                            APPROVE / REVIEW / REJECT
                     (per-document `decision` on DocumentResult is unchanged --
                      it is one of several inputs the case-level policy considers,
                      not the case decision itself)
```

The image is retained as supporting evidence, but Repo 1.0 does not perform layout-aware
vision inference. The deterministic OCR sidecar simulates the text stream that a legacy
OCR engine would have produced. Since stage P1, that sidecar text is additionally routed
through a typed Document Intelligence provider interface (`src/document_intelligence/`)
that produces schema-validated, provenance-carrying `DocumentEvidence`/`EvidenceField`
records (see `docs/data_dictionary.md`).

**As of stage P5, case-level decisioning is fully rearchitected.** `CaseResult.decision`
is no longer "the worst individual document decision" — it is the explicit output of
`src/decision_policy/`, an inspectable, deterministic policy that aggregates evidence
from every prior stage (Document Intelligence, Identity Resolution, Evidence Validation,
Fraud Signals) into `RiskFactor` objects, then applies a simple, testable rule: any
hard-stop factor → REJECT; any remaining factor → REVIEW; no factors → APPROVE. See
`docs/data_dictionary.md` for the full contract and `docs/assessment/` for the original
P0 finding this closes.

## Current brownfield constraints (status as of P5)

1. ~~Parsing logic is document-type specific and brittle.~~ The legacy regex/line parser
   (`src/parser.py`) is unchanged and still brittle; the classification layer (P1)
   softens this only for document-type identification, not field-label parsing itself.
2. ~~Confidence is based on field completeness, not calibrated model confidence.~~ The
   legacy `completeness` score is unchanged. `evidence.fields[*].confidence` (P1) is a
   separate, deterministic heuristic, explicitly not a calibrated probability. P5's
   `risk_assessment.evidence_strength`/`uncertainty` are further separate, also
   explicitly not calibrated probabilities — see `docs/data_dictionary.md`.
3. **RESOLVED as of stage P5** (was: "case verification is merely an aggregation of
   document results; it does not perform robust entity resolution"). P2 added
   `identity_resolution` as a reporting-only capability; P5 makes its findings an actual
   input to the case decision via `src/decision_policy/`. Concretely: `CASE-005`
   (`name_variation_ocr_error`) went from `APPROVE` (P0-P4, the documented brownfield
   gap) to `REVIEW` (P5) because its identity-attribute conflict is now a risk factor
   the policy consults. A conflicting date_of_birth specifically is a hard stop
   (`REJECT`); a conflicting name/address alone is review-level, not an automatic
   rejection, since spelling/transliteration variance can plausibly fall below the
   fuzzy-match threshold without being fraudulent (a deliberate, documented policy
   choice, not an oversight).
4. Fraud handling capability is still limited to the same synthetic text marker plus
   signals derived from P1-P3's evidence/validation/identity layers (`src/fraud_signals/`,
   P4) — no pixel-level forensics exists, and P5's policy consumes these signals (a
   CRITICAL-severity fraud signal is a hard stop) without pretending the underlying
   detection capability is any stronger than it is.
5. No provider adapter, reviewer queue, persistence layer, or trace spans.
   `DocumentIntelligenceProvider` (P1) and `DocumentForensicsProvider` (P4) exist as
   provider adapters; reviewer queue, persistence and tracing remain absent. Rule-level
   versioning exists for validation rules (`ValidationResult.rule_version`, P3) and for
   the decision policy itself (`RiskAssessment.policy_version`, P5); there is still no
   versioning of `src/rules.py`'s per-document rules.
6. Validation logic that was embedded in `src/rules.py`'s single `evaluate()` function
   is decomposed into `src/evidence_validation/` (P3) as individually auditable,
   schema-validated rules. `src/rules.py`'s per-document decision logic itself is
   **still unchanged since P0** — it still independently computes
   completeness/expiry/format/tamper for each document, and that per-document decision
   remains one input among several to P5's case-level policy (see constraint 3).
   `config/baseline.json` is genuinely authoritative for `mandatory_fields` and
   `min_field_completeness_for_approve` (via `src/policy.py`, P3).
7. Fraud/anomaly evidence is a distinct subsystem (`src/fraud_signals/`, P4), separated
   from decision policy the way P3 separated validation from decisioning. The hard
   architectural distinction between `FRAUD_SIGNAL_PRESENT` (evidence exists) and
   `FRAUD_PROVEN` (reserved — no code path in this repository can produce it) is
   preserved unchanged by P5: a CRITICAL fraud signal is a hard-stop *input* to the
   policy, but the policy still never claims fraud is *proven*. No LLM is called
   anywhere in this repository, at any stage, for any determination — consequential
   decisions in this repository are 100% deterministic, rule-based Python.
8. **As of stage P5**: `src/decision_policy/` is the first component in this repository
   whose entire purpose is producing the case-level decision from aggregated evidence.
   It is deliberately rule-based rather than a weighted score: every `RiskFactor` has an
   explicit `triggers_hard_stop` boolean set where it is derived, and the policy
   decision is nothing more than "any hard-stop factor → REJECT; any factor →
   REVIEW; no factors → APPROVE" — fully inspectable and testable
   (`tests/test_decision_policy.py`), not an opaque score crossing a threshold.
9. **As of stage P6**: a `REVIEW` decision now has somewhere to go. `src/review/` is a
   SQLite-backed, durable human-in-the-loop workflow (`ReviewCase`, a
   `OPEN`→`IN_REVIEW`→`{RESOLVED,ESCALATED}` state machine, an append-only analyst audit
   log) behind additive `/v1/cases/{id}/reviews` and `/v1/reviews/*` endpoints —
   `/v1/documents/verify` and `/v1/cases/{id}/verify` are completely unaffected. Only
   `REVIEW`-decision cases may enter this workflow. An analyst correction is recorded as
   an annotation on the audit trail, never a rewrite of the original evidence snapshot.
   See `docs/data_dictionary.md`.
10. **As of stage P7**: the transformation from P0 through P6 now has an independent
    evaluation harness (`eval/`, run via `python scripts/run_evaluation.py`) answering
    "did the transformation actually improve system quality without introducing unsafe
    regressions?" — document-intelligence, identity-resolution, decisioning and
    operational metrics against a curated 10-category case set, metamorphic invariance
    and adversarial-sensitivity checks, and release gates that fail the run (non-zero
    exit) if any regress. It is independent of and does not modify `src/` or the
    pytest regression suite. See `docs/data_dictionary.md`.
11. **As of stage P8**: security/privacy hardening at the identity-evidence boundaries,
    not a documentation-only pass. `src/security/` (allowlist identifier validation,
    document-content sanitization, an `Authorizer` abstraction with a deterministic
    workshop implementation, an in-memory rate limiter, an allowlist-field-name logging
    helper) is wired into `src/repository.py`, `src/app.py`, `src/models.py`,
    `src/review/`. Every `/v1/reviews*` endpoint now requires an authenticated
    `reviewer` credential; `/v1/documents/verify` and `/v1/cases/{id}/verify` remain
    open (a documented, deliberate scope boundary). A centralized exception handler
    returns generic, sanitized errors to callers while logging full detail
    server-side. See `docs/security/threat_model.md` and
    `docs/security/privacy_data_flow.md`.
