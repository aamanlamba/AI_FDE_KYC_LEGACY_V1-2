# Synthetic Scenario Catalog

| Case | Scenario | Documents | Baseline learning objective |
|---|---|---|---|
| CASE-001 | clean | passport, national ID, driving licence | Happy path |
| CASE-002 | noisy scan | passport, national ID | Capture degradation exists but sidecar remains deterministic |
| CASE-003 | rotated | driving licence, passport | Image orientation should not be trusted to legacy parser |
| CASE-004 | expired document | passport, national ID | Deterministic expiry gate |
| CASE-005 | name variation + OCR corruption | passport, national ID | Expose that the inherited case aggregation does not reconcile identity/name discrepancies |
| CASE-006 | suspected tampering | passport, driving licence | Synthetic fraud marker must escalate |

All persons and identifiers are fabricated.
