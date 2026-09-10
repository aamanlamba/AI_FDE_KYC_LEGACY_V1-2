# Privacy Data-Flow Inventory — Stage P8

All data in this repository is synthetic (CLAUDE.md rule 6; confirmed throughout
P0-P7). This inventory is engineered as if it were real PII (P8 requirement 20) —
the flows and controls described below are what would matter if the applicant names,
dates of birth, and document numbers in `data/` were real.

## 1. The three-way separation (requirement 8)

Every object in this system's data model falls into exactly one of three categories.
Conflating them is the single most common source of accidental PII exposure, so the
distinction is made explicit here and enforced structurally where practical.

| Category | Examples | Where it lives | May appear in logs? |
|---|---|---|---|
| **Operational identifier** | `case_id`, `document_id`, `review_id`, `correlation_id` | URL paths, `src/security/logging_utils.py`'s allowlist, SQLite primary keys | Yes — these identify a record, they are not identity attributes themselves |
| **Identity attribute** | `full_name`, `date_of_birth`, `address`, `document_number`, `nationality` | `EvidenceField.value`, `ReviewCase.evidence_summary.key_fields`, `IdentityResolutionResult` attribute comparisons | **Never** — not in application logs; only in API responses to an authenticated, authorized caller |
| **Evidence content** | Raw OCR sidecar text, `explanation`/`reason_code` narrative strings that may embed identity-attribute values | `DocumentEvidence.extraction_warnings`, `ValidationResult.explanation`, `FraudSignal.explanation`, `RiskAssessment.explanation`, `ReviewCase.reviewer_summary` | **Never** in logs; sanitized (`sanitize_for_display`) before reaching the reviewer summary specifically (see threat model §12) |

The synthetic dataset's own `case_id`/`document_id` values happen to be pattern-based
(`CASE-001`, `CASE-001-PASSPORT`) and carry no identity information themselves — this
is a property worth preserving deliberately in any future dataset or real deployment:
**operational identifiers must never embed identity attributes** (e.g., never
`document_id = "john-smith-passport"`).

## 2. Data flow

```
Entry points (data/ fixtures in this training repo; a real deployment's equivalent
would be an upload/ingestion API):
  data/applications/*.json      -- submitted_name, submitted_dob, submitted_address
  data/sidecar_ocr/*.txt        -- OCR text (simulates a real OCR engine's output)
  data/input_documents/*.png    -- document images (never read by any code path --
                                    see docs/assessment/architecture_current.md)
        |
        v
src.repository (file read, size-bounded, identifier-allowlisted)
        |
        v
src.document_intelligence -- classification, quality assessment, DocumentEvidence
        |
        +--> src.evidence_validation -- computable-truth checks
        +--> src.identity_resolution -- cross-document/application attribute comparison
        +--> src.fraud_signals       -- signal derivation from the above
        +--> src.decision_policy     -- RiskAssessment, policy_outcome
        |
        v
API response (DocumentResult / CaseResult) -- full identity-attribute content,
returned to whatever called /v1/documents/verify or /v1/cases/{id}/verify
(UNAUTHENTICATED in this stage -- see threat_model.md §10 residual risk)
        |
        v (only if decision == REVIEW, and only via an authenticated 'reviewer' call)
src.review.workflow.open_review_case -- builds a SNAPSHOT (evidence_summary,
discrepancies, fraud_signals, reason_codes) of identity-attribute-bearing content
        |
        v
src.review.store.ReviewStore -- DURABLE PERSISTENCE to var/review_store.sqlite3
(the only place in this system identity attributes are written to disk)
        |
        v
GET /v1/reviews*, POST .../transitions -- authenticated 'reviewer' role required
        |
        v
Analyst corrections -- captured in review_audit_log.correction as a NEW row,
layered on top of the original snapshot, never rewriting it (P6/P8: no silent
rewrite of evidence -- see docs/data_dictionary.md's ReviewCase immutability note)
```

Logs (`src/app.py`'s correlation middleware) branch off at every step but only ever
carry `method`, `path`, `status`, `correlation_id` — operational identifiers and HTTP
metadata, never identity attributes or evidence content (verified by test, see threat
model §6).

## 3. Data at rest

**Before stage P6**: none. Every computation was stateless, recomputed fresh on every
API call, nothing written to disk beyond the read-only `data/` fixtures.

**Since stage P6**: `var/review_store.sqlite3` — the only durable PII-bearing store in
this system. Contains, per review: `evidence_summary.key_fields` (names, DOBs),
`discrepancies` and `fraud_signals` (free text that may embed identity attributes),
plus the full analyst audit trail (`analyst_action`, `correction`, `rationale`
strings, which an analyst could in principle also type identity attributes into).

- **Not encrypted at rest.** A real deployment handling real PII would need
  encryption at rest (e.g., SQLCipher, or the database moved to a managed service with
  disk-level encryption) plus key management this workshop-scoped repository has no
  infrastructure for. Documented here as a residual risk, not implemented.
- **Access control**: gated behind `Authorizer`/`require_reviewer` (threat model §10) —
  only an authenticated `reviewer`-role credential can read or write review records.
- **Location**: gitignored (`var/`), never committed.

## 4. Retention and deletion boundaries (requirement 17)

| Data | Current retention | Deletion mechanism |
|---|---|---|
| `data/*` fixtures | Indefinite (synthetic training data, version-controlled) | N/A — not real PII, not a retention concern |
| API responses (`DocumentResult`/`CaseResult`) | Not persisted at all — computed fresh, returned, and discarded once the HTTP response is sent | N/A — nothing to delete |
| `review_cases` / `review_audit_log` rows | **Indefinite by default.** No automatic expiry, no scheduled purge job exists in this repository. | `ReviewStore.purge_review(review_id)` (added in P8) hard-deletes a review and its full audit trail. **Not exposed via any API endpoint in this stage** — it is a tested, working primitive (`tests/test_security.py::test_purge_review_*`) an operator or a future admin-authenticated endpoint would call. This is a deliberate, documented scope boundary: building the deletion *primitive* was in scope for this stage; building a self-service deletion *endpoint* (with its own authorization question — should a reviewer delete their own review? does deletion need a second approver?) was judged to need its own design pass, not a rushed addition here. |
| Application logs | Governed by the deployment's log retention policy (out of this repository's control — it only controls what is logged, not how long the log platform retains it) | Out of scope — no identity attributes are logged in the first place (threat model §6), so log retention is not a PII retention concern for this system specifically |

**What a real deployment would need beyond this**: a data retention policy with a
defined maximum age for `RESOLVED`/`ESCALATED` reviews, a scheduled job calling
`purge_review()` (or a bulk equivalent) past that age, and a legal/compliance-reviewed
answer to "does purging a review also need to purge references to it elsewhere?" (this
repository has no other durable store that references a `review_id`, so today the
answer is no — but this should be re-verified if a future stage adds one).

## 5. Cross-reference

See `docs/security/threat_model.md` for the full threat model this inventory
complements, and `docs/data_dictionary.md` for the field-by-field API/persistence
contract this document's categories (§1) apply to.
