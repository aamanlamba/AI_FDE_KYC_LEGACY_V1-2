# Brownfield Baseline Assessment — Repo 1.0 (P0)

Assessment date: 2026-09-10
Assessor mode: read-only forensic inspection + reproduction. No application behaviour was
changed to produce this document (see `git status` / diff at HEAD `5782d8b`).

## 1. Scope and method

This is a baseline assessment only. Per workshop instructions, **no modernization,
Document Intelligence, identity resolution, fraud modelling, risk scoring or HITL work
was implemented in this pass.** Every claim below is backed by either a file/line
reference, a command that was actually executed in this environment, or a reproduced
test/scenario result.

Verification environment: fresh `.venv` created in the repo root, dependencies installed
from `requirements.txt` exactly as pinned, Python 3.14.7 (newer than the 3.11–3.13 range
documented in `WORKSHOP_RUNBOOK.md`; `scripts/workshop_preflight.py` only hard-fails below
3.11, so this was accepted and noted as a risk in `risk_register.md`).

## 2. Commands executed and results

| Step | Command | Result |
|---|---|---|
| Preflight | `python scripts/workshop_preflight.py` | `PREFLIGHT PASSED` (dependency versions match release-tested set) |
| Sanity check | `python scripts/sanity_check.py` | `SANITY CHECK PASSED: 6 cases, 13 documents, images/JSON/sidecars consistent, expected outputs stable, all baseline flows executable` (2.18s) |
| Test suite | `python -m pytest -q` | `22 passed, 1 warning in 0.30s` (warning is an upstream `starlette`/`anyio` deprecation notice, not a test failure) |
| Live smoke test | `python scripts/smoke_server.py` | `SMOKE SERVER PASSED on ephemeral localhost port 54550` (real Uvicorn process, real HTTP calls) (2.51s) |
| Demo run | `python scripts/run_demo.py` | Printed decision/reason codes for all 6 cases — see `behavioural_baseline.md` for the full table |

All four gating commands documented in `README.md` / `WORKSHOP_RUNBOOK.md` pass on this
checkout with no modification.

## 3. What exists today (verified by direct inspection)

- FastAPI app (`src/app.py`, 42 lines) exposing `GET /health/live`, `GET /health/ready`,
  `GET /v1/cases`, `POST /v1/documents/verify`, `POST /v1/cases/{case_id}/verify`, plus
  Swagger UI at `/docs` (confirmed live via `smoke_server.py`).
- A correlation-ID middleware that echoes/generates `x-correlation-id` and logs
  method/path/status/correlation_id per request (`src/app.py:12-17`). No request/response
  body fields (names, DOB, document numbers) are written to logs.
- A repository layer (`src/repository.py`, 35 lines) that loads synthetic JSON/text from
  `data/` by identifier, with a path-traversal guard (`safe_id`, rejects `/`, `\`, `..`).
- A deterministic "OCR" seam (`src/ocr.py`) that is a **1-line passthrough** to a
  pre-written `.txt` sidecar file — it does not read pixels from the corresponding PNG at
  all. Confirmed by `grep -rn "PIL\|Image\|\.png" src/` returning zero matches: no module
  under `src/` ever opens an image.
- A line-prefix/regex parser (`src/parser.py`, 19 lines) keyed off a hard-coded
  `PREFIXES` dict of 8 exact label strings.
- A rules engine (`src/rules.py`, 33 lines) that computes a completeness ratio over 4
  mandatory fields, validates document-number format by regex per type, checks expiry
  against a **frozen reference date** (`REFERENCE_DATE = date(2026, 9, 9)`), and detects
  "tampering" via a literal substring search (`'ALTERED_TEXT_REGION_DETECTED' in raw_text`).
- A service layer (`src/service.py`, 22 lines) that composes OCR → parse → rules for a
  single document, and aggregates a case as `max(rank)` over its documents' decisions with
  no other cross-document logic.
- 6 synthetic applicant cases, 13 synthetic documents, matching PNG images (visibly
  labelled `SYNTHETIC` / `NOT A REAL ID` / `TRAINING DATA ONLY` on their face — confirmed
  by rendering `data/input_documents/CASE-001-PASSPORT.png`), OCR sidecars, ground truth,
  and byte-for-byte expected baseline outputs.
- 22 automated tests across `tests/test_api.py`, `tests/test_rules.py`,
  `tests/test_service.py`, `tests/test_release_integrity.py` — all pass.
- Docker packaging (`Dockerfile`) — not build-verified in this environment (no Docker
  daemon available here, consistent with the caveat already recorded in
  `docs/qa_release_report.md`); the image spec was inspected only.

## 4. Headline finding

The single most consequential, reproducible finding from this pass: **`CASE-005`
(`name_variation_ocr_error`) APPROVEs today**, despite:
- the applicant's passport reading `Mohammed Rahman` and their national ID reading
  `Moharnmad Rehrnan` (an OCR-corrupted rendering of `Mohammad Rehman`),
- both documents individually satisfying all rules (100% mandatory-field completeness,
  valid formats, unexpired, no tamper marker),
- **no code path in the current system ever compares names, DOB, or any other field
  across a case's documents.**

`verify_case` (`src/service.py:16-22`) only takes the worst of the independent
per-document decisions; it does not reconcile identity across documents. This is called
out explicitly in the codebase itself: `tests/test_service.py:8-9` asserts the APPROVE
outcome with the inline comment `# critical weakness: no cross-document/name
reconciliation`, and `CaseResult.limitation_notice` (`src/models.py:24`, populated in
`src/service.py:22`) states the same limitation in every API response. See
`behavioural_baseline.md` and `risk_register.md` for full detail and severity.

## 5. Explicit non-claims

- Passing tests and passing sanity/preflight checks demonstrate **reproducibility and
  stability of currently-documented legacy behaviour**. They are not evidence that the
  behaviour is fit for a production identity-verification decision. `docs/qa_release_report.md`
  already states this; this assessment independently confirms it by reproducing the
  APPROVE outcome on `CASE-005` and `CASE-004-NID`'s sibling-document blind spot (§ below).
- No performance/load claim in `docs/business_problem_statement.md` (20k applications/day,
  15 req/sec peak) has been validated against a realistic deployment. A single-process,
  single-threaded in-process microbenchmark in this environment measured ~22.8k
  `verify_document` calls/sec and ~2.9k `verify_case` calls/sec with no I/O contention,
  no concurrency, no ASGI/network overhead, and a 13-document dataset held in the OS page
  cache — this number is not a substitute for a real load test and is reported only as a
  lower-bound sanity check that the deterministic code path itself is not the bottleneck.

## 6. Companion documents

- `architecture_current.md` — verified runtime flow and coupling map.
- `risk_register.md` — categorized, severity-ranked risk findings with evidence.
- `behavioural_baseline.md` — per-case/per-document measurable results, incident
  verification against implementation, and test inventory.
- `modernization_backlog.md` — candidate backlog derived from the above, explicitly not
  actioned in this pass.
- `baseline_results.json` — machine-readable version of the behavioural baseline table.
