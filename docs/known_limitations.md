# Known Limitations and Technical Debt

The following issues are known in the inherited system. They describe the current condition only; they do not prescribe a particular remediation.

- OCR is represented by deterministic sidecar text rather than inference from document pixels.
- No layout or bounding-box understanding is present.
- Regex and line-prefix parsing is brittle and document-type specific.
- No reliable document-authenticity capability exists. As of stage P4, this is now
  architecturally explicit rather than implicit: `src/fraud_signals/` reports fraud
  *signals* (evidence), never a fraud *verdict*, via a `DocumentForensicsProvider`
  interface whose only implementation today is a literal text-marker scan — not
  pixel-level forensics, which this repository has no capability to perform (its OCR
  layer never reads image pixels at all). See `docs/data_dictionary.md`.
- Cross-document identity consistency is weak. **RESOLVED as a decision input as of
  stage P5**: `src/identity_resolution/` (P2) reports attribute-level match status, and
  `src/decision_policy/` (P5) now consults it — a conflicting `date_of_birth` is a hard
  stop (REJECT), any other identity conflict/fuzzy-match/insufficient-evidence is
  review-level. `CASE-005` (the case this exact gap was demonstrated on) now correctly
  reaches `REVIEW` instead of silently `APPROVE`-ing. See `docs/data_dictionary.md`.
- No transliteration or locale-aware name normalization exists.
- Confidence is a heuristic completeness ratio rather than a calibrated probability.
  P5's `risk_assessment.evidence_strength`/`uncertainty` are further, separate
  heuristics — also explicitly not calibrated probabilities (see `docs/data_dictionary.md`).
- Case results are driven by simple document-result aggregation. **RESOLVED as of stage
  P5**: `CaseResult.decision` is now the explicit output of `src/decision_policy/`'s
  rule-based policy, not "the worst individual document decision." Per-document
  decisions (`src/rules.py`, unchanged since P0) remain one input among several.
- Tamper detection is limited to a synthetic marker in the training data. As of stage
  P4, `src/rules.py`'s decision-relevant tamper check is unchanged (still the same
  literal marker match, now sourced from a shared `TAMPER_MARKER` constant), and a
  separate, additive `src/fraud_signals/` layer reports the same finding as a labeled,
  traceable `FraudSignal` (category `tamper_marker`, source
  `deterministic_marker_forensics:sidecar_text_substring_match`) alongside other
  offline-derivable signals (temporal impossibilities, identity conflicts, document
  duplication) — but this remains the same underlying synthetic-marker detection
  capability, not real forensics.
- No external identity, registry or watchlist integration exists.
- There is no durable human-review queue or evidence-review interface. **RESOLVED as of
  stage P6**: `src/review/` is a SQLite-backed durable review workflow (`ReviewCase`,
  `OPEN`/`IN_REVIEW`/`RESOLVED`/`ESCALATED` states, an append-only audit log of analyst
  actions) behind additive `/v1/cases/{id}/reviews` and `/v1/reviews/*` endpoints. Only
  `REVIEW`-decision cases may open an ordinary review (see `docs/data_dictionary.md`).
- There is no durable audit datastore. **Partially addressed as of stage P6**: analyst
  review actions are now durably, immutably logged (`review_audit_log`, insert-only).
  Case *verification* itself (`/v1/cases/{id}/verify`) remains fully stateless/computed
  fresh on every call, as it has since P0 — there is still no durable store of
  verification decisions themselves, only of review-workflow actions taken on them.
- Logging is basic and does not provide distributed transaction tracing. **PII exposure
  addressed as of stage P8**: `src/security/logging_utils.py` provides an
  allowlist-of-field-names logging helper, and a direct test
  (`tests/test_security.py::test_request_logging_never_includes_identity_attribute_values`)
  confirms no identity attribute appears in captured log output. Distributed tracing
  itself remains absent.
- No application metrics endpoint or formal SLO monitoring exists.
- No rate limiting, authentication, authorization or tenant isolation is implemented in
  the training service. **Partially addressed as of stage P8**: `src/security/auth.py`
  (deterministic, config/env-driven `Authorizer`) and `src/security/limits.py`
  (in-memory rate limiter) now gate every `/v1/reviews*` endpoint. `/v1/documents/verify`
  and `/v1/cases/{id}/verify` remain open — a documented, deliberate scope boundary
  (see `docs/security/threat_model.md` §10), not an oversight. Tenant isolation is not
  addressed at all.
- No cryptographic document-signature or checksum verification exists. As of stage P3,
  this is now honestly disclosed rather than silently absent: `src/evidence_validation/`
  reports a `CHECKSUM-SIGNATURE` rule with status `NOT_IMPLEMENTED` (a status distinct
  from `PASS`/`FAIL`, reserved for capability-boundary disclosure) rather than fabricating
  a result.
- Privacy retention and deletion controls are not implemented in application code.
  **Partially addressed as of stage P8**: `ReviewStore.purge_review()` is a tested,
  working hard-delete primitive for the only durable PII-bearing store in this system
  (`var/review_store.sqlite3`, introduced in P6). No scheduled/automatic purge job and
  no API endpoint expose it yet — see `docs/security/privacy_data_flow.md` §4 for the
  full retention/deletion boundary and why this split was made deliberately.
- Error handling is uneven across parsing and validation paths. **Partially addressed
  as of stage P8**: a centralized `Exception` handler in `src/app.py` now catches any
  exception not matched by a more specific handler, logs it in full server-side with
  the request's correlation ID, and returns a generic, sanitized `500` to the caller —
  never a stack trace or internal detail. Per-path error handling elsewhere is otherwise
  unchanged.
- Several business decisions are encoded directly in Python conditionals. As of stage
  P5, the case-level decision policy (`src/decision_policy/`) is still plain Python
  conditionals by deliberate choice (requirement: avoid opaque weighted scoring) — but
  it is now one small, named, versioned, directly-tested rule set
  (`src/decision_policy/engine.py`, `RiskAssessment.policy_version`) rather than logic
  buried inside a single per-document function.
- Changes to document formats can require code changes and regression retesting.
- `config/baseline.json` records expected baseline settings, but the legacy rule engine
  still hard-codes several of those values rather than consuming the file as authoritative
  runtime configuration. As of stage P3, `src/policy.py` loads `mandatory_fields`,
  `supported_document_types` and `min_field_completeness_for_approve` from this file
  (falling back to the historical hard-coded values if it is absent), and both
  `src/rules.py` and `src/evidence_validation/` now consume those config-sourced values.
  Document-number format regexes (`src/rules.py:PATTERNS`) remain code-level structural
  constants, not config — they describe the shape of a document format, not a business
  policy threshold, so externalizing them was judged out of scope for this stage.
