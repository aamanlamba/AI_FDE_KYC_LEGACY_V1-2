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
       Validation rules                      + schema-validated DocumentEvidence
     date / ID / tamper flag                             |
     (src/rules.py, unchanged                +------------+------------+
      decision policy)                       v                         v
                |                 Evidence Validation engine   Identity Resolution
                |                 (src/evidence_validation/)   (src/identity_resolution/)
                |                 10 computable-truth rule     cross-document attribute
                |                 categories, PASS/FAIL/        matching (P2, unchanged
                |                 UNKNOWN/NOT_APPLICABLE/       in this stage)
                |                 NOT_IMPLEMENTED per rule
                |                            |
                |               attached additively to the API
                |               response as `validation` (not yet
                |               consumed by decisioning)
                v
     APPROVE / REVIEW / REJECT
```

The image is retained as supporting evidence, but Repo 1.0 does not perform layout-aware
vision inference. The deterministic OCR sidecar simulates the text stream that a legacy
OCR engine would have produced. As of stage P1, that sidecar text is additionally routed
through a typed Document Intelligence provider interface
(`src/document_intelligence/`) that produces schema-validated, provenance-carrying
`DocumentEvidence`/`EvidenceField` records (see `docs/data_dictionary.md`). This is an
additive evidence-generation capability only — the decision path (`src/rules.py`) is
unchanged and does not consume it yet; a real OCR/VLM provider could later replace the
deterministic provider behind the same interface without any change to decisioning.

## Current brownfield constraints
1. ~~Parsing logic is document-type specific and brittle.~~ The legacy regex/line parser
   (`src/parser.py`) is unchanged and still brittle; the new classification layer softens
   this only for document-type identification (declared-label + document-number-pattern
   cross-check, with an explicit `unknown` outcome), not for field-label parsing itself.
2. ~~Confidence is based on field completeness, not calibrated model confidence.~~ The
   legacy `completeness` score is still a raw ratio (unchanged). The new `evidence.fields[*].confidence`
   is a *different*, additive, deterministic heuristic derived from document quality and
   per-field format validation — it is also not a calibrated probability, and this is
   stated explicitly in `docs/data_dictionary.md`.
3. Case verification is merely an aggregation of document results; it does not perform
   robust entity resolution. **As of stage P2, this is partially addressed**: an explicit
   `src/identity_resolution/` capability now compares full_name/date_of_birth/address
   across the submitted application and every document's evidence and reports a
   `CONFLICT`/`FUZZY_MATCH`/`NORMALIZED_MATCH`/`EXACT`/`INSUFFICIENT_EVIDENCE` verdict
   (see `docs/data_dictionary.md`). The `decision` field itself still does not consult
   this result — case-level APPROVE/REVIEW/REJECT remains the unchanged worst-of-documents
   policy, pending a later risk-policy stage.
4. Fraud handling is limited to obvious synthetic markers. **Unchanged in this stage by
   design** — the Document Intelligence layer assesses capture quality only, not
   authenticity/tampering, to avoid scope creep into decisioning.
5. No provider adapter, reviewer queue, persistence layer, trace spans or policy
   versioning. A provider adapter now exists for document evidence extraction
   (`DocumentIntelligenceProvider`); reviewer queue, persistence, tracing and policy
   versioning remain absent. Rule-level versioning now exists for validation rules
   (`ValidationResult.rule_version`), but there is still no versioning of the overall
   decision policy in `src/rules.py`.
6. **As of stage P3**: validation logic that was embedded in `src/rules.py`'s single
   `evaluate()` function (format checks, expiry handling, mandatory-field completeness)
   is now decomposed into `src/evidence_validation/` as individually auditable,
   schema-validated rules (10 categories, each result carrying `rule_id`, `severity`,
   `reason_code`, `explanation` and `evidence_references`). `src/rules.py` itself is
   **unchanged in its decision logic** — it still independently computes
   completeness/expiry/format/tamper and maps them to APPROVE/REVIEW/REJECT exactly as
   before; the new validation layer runs alongside it, not underneath it, in this stage.
   `config/baseline.json` is now genuinely authoritative for `mandatory_fields` and
   `min_field_completeness_for_approve` (via `src/policy.py`), partially closing a gap
   the P0 baseline assessment flagged.
