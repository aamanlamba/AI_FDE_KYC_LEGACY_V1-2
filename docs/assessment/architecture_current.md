# Current Architecture — Repo 1.0 (verified)

This supersedes nothing in `docs/system_context.md`; it adds line-level evidence and one
correction (§3).

## 1. Verified runtime flow

```text
HTTP request (FastAPI, src/app.py)
        |
        v
correlation middleware (assigns/echoes x-correlation-id, logs method/path/status)
        |
        v
src/service.py: verify_document(document_id) or verify_case(case_id)
        |
        +--> src/repository.py: load_application() / load_sidecar()   [reads data/*.json, data/sidecar_ocr/*.txt]
        |         - safe_id() blocks '/', '\\', '..' in identifiers
        |         - unknown id -> FileNotFoundError -> HTTP 404 (src/app.py:19-21)
        |         - invalid id  -> ValueError        -> HTTP 400 (src/app.py:23-25)
        |
        v
src/ocr.py: extract_text(document_id)
        - pure passthrough to repository.load_sidecar(); no pixel/image processing
        |
        v
src/parser.py: parse_legacy_ocr(text)
        - line-by-line, exact-prefix match against an 8-entry PREFIXES dict
        - unmatched ':'-containing lines (excluding 4 known marker prefixes) become
          warnings 'UNPARSED_LINE:<first 40 chars>'
        - text-level substring checks add 'DEGRADED_OCR_QUALITY' / 'ROTATED_CAPTURE'
          parse warnings
        |
        v
src/rules.py: evaluate(fields, raw_text) + completeness(fields)
        - completeness = fraction of 4 mandatory fields present (full_name, date_of_birth,
          document_number, expiry_date)
        - per-type document-number regex check
        - expiry check against a FROZEN reference date (2026-09-09)
        - tamper check = literal substring 'ALTERED_TEXT_REGION_DETECTED' in raw OCR text
        - decision: REJECT if tamper or expired; REVIEW if any other reason/warning;
          else APPROVE
        |
        v
DocumentResult (src/models.py) — for /v1/documents/verify
        |
        v  (only for /v1/cases/{id}/verify)
src/service.py: verify_case()
        - loads application JSON (document_ids list)
        - calls verify_document() once per document_id, independently
        - case decision = max(rank) over document decisions (APPROVE=0, REVIEW=1, REJECT=2)
        - case reason_codes = union of all document reason_codes
        - NO field-level comparison across documents of any kind
        |
        v
CaseResult (src/models.py), always carrying a fixed limitation_notice string
```

## 2. Module coupling map

| Module | Depends on | Notes |
|---|---|---|
| `app.py` | `models`, `service`, `repository` | Thin; no business logic. Exception handlers are type-based (`FileNotFoundError`→404, `ValueError`→400), which means **any** `ValueError` raised anywhere in the call chain — not just identifier validation — becomes a generic 400 to the caller. |
| `service.py` | `ocr`, `parser`, `rules`, `repository`, `models` | Orchestration only; owns the case-aggregation policy (`RANK` dict) directly in code, not in `config/baseline.json`. |
| `parser.py` | none (pure function over a string) | Fully deterministic and unit-testable in isolation; also fully coupled to the exact sidecar label vocabulary. |
| `rules.py` | none (pure function over `(fields, raw_text)`) | Contains the only two "policy" gates that are true rejections (expiry, tamper) and the only completeness threshold (0.75, mirrored in `config/baseline.json` but not read from it — see `known_limitations.md` line 25, confirmed by literal `0.75` at `src/rules.py:19`). |
| `repository.py` | filesystem under `data/` | Sole trust boundary for path traversal; also the sole point where "unknown identifier" and "malformed identifier" are distinguished. |
| `ocr.py` | `repository.load_sidecar` | Named an OCR seam but performs no OCR; it is a label for where a real OCR/VLM adapter would later be inserted. |

## 3. Correction to `docs/system_context.md`

`docs/system_context.md:24` states: *"The image is retained as supporting evidence, but
Repo 1.0 does not perform layout-aware vision inference."* This is accurate as far as it
goes, but understates the gap: **the image is not read by any code path at all**, layout-aware
or otherwise. `grep -rn "PIL\|Image\|\.png" src/*.py` returns no matches. The only code that
opens document images is test/ops tooling — `tests/test_release_integrity.py:18-19` and
`scripts/sanity_check.py:97-105` — both of which only call `Image.verify()` to confirm the
PNG is well-formed, not to extract or validate any content from it. Consequently:

- `DocumentResult` / `CaseResult` (`src/models.py`) carry no reference to the source image
  (no path, hash, or checksum field).
- There is no way, from a `DocumentResult` alone, to prove which image produced a given
  sidecar/decision, or to detect that a sidecar and its image have been swapped.
- The "supporting evidence" image is evidentiary only in the sense that it sits on the
  same filesystem next to the case; it is not linked to the decision record.

This is treated as a risk in `risk_register.md` (evidence-integrity / explainability
category), not merely a known limitation, because CLAUDE.md rule 13 ("every important
decision must be explainable from retained evidence") and rule 9 ("do not silently
discard evidence") both bear on it directly.

## 4. What is and is not configuration-driven

`config/baseline.json` declares `min_field_completeness_for_approve: 0.75`,
`reject_if_expired: true`, `reject_if_tamper_marker: true`, `review_if_parse_errors: true`,
and the supported document types. In the running code:

| Config key | Actually consumed by `src/`? | Evidence |
|---|---|---|
| `supported_document_types` | Indirectly, via `PATTERNS` dict keys in `rules.py:6-10`, but hard-coded there, not loaded from the file | `src/rules.py` has no `import json` / no read of `config/` |
| `min_field_completeness_for_approve` | No — hard-coded literal `0.75` | `src/rules.py:19` |
| `reject_if_expired`, `reject_if_tamper_marker`, `review_if_parse_errors` | No — hard-coded control flow | `src/rules.py:26-32` |
| `offline_ocr_mode` | Only read by `scripts/sanity_check.py` and `scripts/workshop_preflight.py` for validation, never by `src/` | `src/` has no reference to `config/baseline.json` at all |

`config/baseline.json` is currently **documentation of intended policy**, not an input to
the running service. Nothing in `src/` opens that file. This is the concrete evidence
behind `known_limitations.md` line 25.
