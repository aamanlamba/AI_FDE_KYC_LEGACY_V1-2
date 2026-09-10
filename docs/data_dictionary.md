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
