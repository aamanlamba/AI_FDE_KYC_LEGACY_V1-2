# ADR-005: Shared domain constants live in `src/policy.py`, not `src/rules.py`

**Status**: Accepted (P10)

## Context
P10's coupling review (an actual AST-based import-graph check, not just inspection —
see `tests/test_architecture.py`) found that `src/document_intelligence/`,
`src/evidence_validation/`, and `src/fraud_signals/` all imported `PATTERNS`
(document-number regex per type) and/or `TAMPER_MARKER` from `src/rules.py`.
`src/rules.py` is conceptually the decisioning layer (P0's original per-document
`evaluate()` function, still unchanged in logic since P0) — three unrelated layers
(extraction, validation, fraud) depending on decisioning's own module for values that
belong to none of them specifically is a layering violation, even though it never
produced a circular import.

## Decision
Move `PATTERNS` and `TAMPER_MARKER` into `src/policy.py` — already the established,
dependency-free leaf module every layer safely imports config-driven values from
(`MANDATORY_FIELDS`, `SUPPORTED_DOCUMENT_TYPES`, `MIN_FIELD_COMPLETENESS_FOR_APPROVE`
since P3). `src/rules.py` now imports them back from `policy.py` alongside every other
consumer, rather than owning them.

## Consequences
- Pure constant relocation: identical values, zero logic changes. Verified
  behavior-neutral by running the full regression suite unchanged before touching any
  consumer, and again after every file was updated.
- `document_intelligence` and `fraud_signals` no longer import from `rules` at all.
  `tests/test_architecture.py::test_document_intelligence_does_not_depend_on_decisioning_module`
  guards against this regressing.
- `src/evidence_validation/engine.py` still imports `REFERENCE_DATE` from `rules.py` —
  considered and left alone. `REFERENCE_DATE` is a reproducibility anchor decisioning
  actually owns (the frozen "now" for expiry/temporal checks), not a shared domain fact
  like a document-number format; the dependency is judged conceptually sound, and "do
  not rewrite solely for aesthetic reasons" argues against touching a working,
  unproblematic relationship just for symmetry.
