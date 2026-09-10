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
                v
       Regex / line parser
                |
                v
       Validation rules
     date / ID / tamper flag
                |
                v
     APPROVE / REVIEW / REJECT
```

The image is retained as supporting evidence, but Repo 1.0 does not perform layout-aware vision inference. The deterministic OCR sidecar simulates the text stream that a legacy OCR engine would have produced.

## Current brownfield constraints
1. Parsing logic is document-type specific and brittle.
2. Confidence is based on field completeness, not calibrated model confidence.
3. Case verification is merely an aggregation of document results; it does not perform robust entity resolution.
4. Fraud handling is limited to obvious synthetic markers.
5. No provider adapter, reviewer queue, persistence layer, trace spans or policy versioning.
