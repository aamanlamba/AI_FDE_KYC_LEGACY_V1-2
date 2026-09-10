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
