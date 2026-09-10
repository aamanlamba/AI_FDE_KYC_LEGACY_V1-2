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
| parsed_fields | Values extracted from OCR sidecar |
| completeness | Fraction of mandatory fields present |
| warnings | Parser/validation warnings |
| source | Indicates deterministic sidecar OCR |
