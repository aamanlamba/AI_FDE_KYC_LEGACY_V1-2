# Known Limitations and Technical Debt

The following issues are known in the inherited system. They describe the current condition only; they do not prescribe a particular remediation.

- OCR is represented by deterministic sidecar text rather than inference from document pixels.
- No layout or bounding-box understanding is present.
- Regex and line-prefix parsing is brittle and document-type specific.
- No reliable document-authenticity capability exists.
- Cross-document identity consistency is weak.
- No transliteration or locale-aware name normalization exists.
- Confidence is a heuristic completeness ratio rather than a calibrated probability.
- Case results are driven by simple document-result aggregation.
- Tamper detection is limited to a synthetic marker in the training data.
- No external identity, registry or watchlist integration exists.
- There is no durable human-review queue or evidence-review interface.
- There is no durable audit datastore.
- Logging is basic and does not provide distributed transaction tracing.
- No application metrics endpoint or formal SLO monitoring exists.
- No rate limiting, authentication, authorization or tenant isolation is implemented in the training service.
- No cryptographic document-signature or checksum verification exists.
- Privacy retention and deletion controls are not implemented in application code.
- Error handling is uneven across parsing and validation paths.
- Several business decisions are encoded directly in Python conditionals.
- Changes to document formats can require code changes and regression retesting.
- `config/baseline.json` records expected baseline settings, but the legacy rule engine still hard-codes several of those values rather than consuming the file as authoritative runtime configuration.
