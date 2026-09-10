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
