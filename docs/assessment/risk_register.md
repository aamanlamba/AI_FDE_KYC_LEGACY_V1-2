# Risk Register — Repo 1.0 Baseline

Severity legend: **Critical** (wrong identity decision possible with no operator visibility),
**High** (material decision-quality or operational gap), **Medium** (quality/observability
gap that degrades trust or maintainability), **Low** (hygiene/hardening gap not currently
exercised by the dataset).

Each row cites the file/line or reproduction evidence backing the claim.

## Identity consistency

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-01 | **Critical** | No cross-document identity reconciliation exists. A case with materially different names/DOB across its documents can APPROVE if each document individually passes. | `src/service.py:16-22` (no field comparison); reproduced live: `verify_case('CASE-005')` → `APPROVE` with passport `Mohammed Rahman` vs national ID `Moharnmad Rehrnan`; `tests/test_service.py:8-9` codifies this as expected/passing behaviour with an inline admission (`critical weakness`). |
| R-02 | High | `submitted_name` / `submitted_dob` on the application record (`data/applications/*.json`) are never compared against any parsed document field. Onboarding-form spoofing relative to the documents themselves is structurally undetectable. | `src/service.py:16-22` never reads `app['submitted_name']` or `app['submitted_dob']`, only `app['document_ids']`. |
| R-03 | Medium | No transliteration/locale-aware normalization exists, so even legitimate spelling variants (e.g., `Mohammed` vs `Mohammad`) would fail any naive equality check a future fix might add without design care. | `docs/known_limitations.md:10`; confirmed no normalization code exists anywhere in `src/`. |

## Parser / extraction brittleness

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-04 | High | Field extraction is keyed to 8 exact-string line prefixes (`DOCUMENT TYPE:`, `NAME:`, etc.). Any upstream OCR/vendor change to label wording, casing, punctuation, or language silently drops that field from `parsed_fields` with no error — the field is simply absent. | `src/parser.py:1-15`; a missing field only surfaces indirectly via a lower `completeness` score, never as its own diagnosable warning. |
| R-05 | Medium | Non-prefixed but colon-containing lines produce a truncated, low-detail warning (`UNPARSED_LINE:<first 40 chars>`) with no field name, raw context beyond 40 chars, or indication of which mandatory field (if any) was affected. | `src/parser.py:15-16`. |
| R-06 | Medium (confirmed **not** reproducible on current dataset, so severity is forward-looking) | INC-163 ("parser required code change after upstream format variation") is a structural certainty of this design, not a one-off: adding a new document type or renaming a label requires editing `PREFIXES` and `PATTERNS` and redeploying. | `src/parser.py:1-5`, `src/rules.py:6-10`. |
| R-07 | Low | `OCR_QUALITY: DEGRADED` and `CAPTURE_ORIENTATION: 90_DEGREES` are detected as **exact substrings of the whole sidecar text**, once in `parser.py` (as a warning) and again independently in `rules.py` (as a second, differently-named warning). This produces duplicate-looking warnings (`DEGRADED_OCR_QUALITY` and `OCR_QUALITY_DEGRADED` both present) for one underlying condition. | `src/parser.py:17-18`, `src/rules.py:29-30`; reproduced: `verify_document('CASE-002-PASSPORT').warnings == ['DEGRADED_OCR_QUALITY', 'OCR_QUALITY_DEGRADED']`. |

## Decisioning weaknesses / hard-coded policy

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-08 | High | All policy thresholds (`0.75` completeness gate, expiry/tamper reject gates, document-type regexes) are Python literals inside `rules.py`, not sourced from `config/baseline.json` despite that file appearing to be the authoritative policy config. Changing policy requires a code change + full retest, not a config change. | `src/rules.py:6-10,19,26-32`; confirmed by `grep` returning zero references to `config/` anywhere in `src/`. See `architecture_current.md` §4. |
| R-09 | High | "Tamper detection" is a single literal substring match (`'ALTERED_TEXT_REGION_DETECTED' in raw_text`) against the deterministic OCR text stream. It has no relationship to the document image, any forensic signal, or any pattern more general than the exact training-data marker string. It is trivially defeated by any rewording and cannot fire on genuine, unlabelled tampering. | `src/rules.py:28`. |
| R-10 | Medium | Completeness is a raw fraction of 4 mandatory fields present/absent — a proxy for form-completeness, not a calibrated confidence measure. A document with all 4 fields present but every value wrong (e.g., OCR-swapped digits within a still-valid-format document number) scores identically to a perfectly correct one. | `src/rules.py:12-13`; confirmed no per-field confidence or cross-check against ground truth exists in the decision path (ground truth is only used by tests/sanity tooling, never by `src/`). |
| R-11 | Medium | `review_if_parse_errors` in config implies parse errors *should* drive REVIEW, but in the actual rule (`rules.py:32`) *any* warning (including benign ones like a rotation marker) forces REVIEW with an undifferentiated `MANUAL_REVIEW_REQUIRED` reason code — an analyst cannot tell from reason codes alone whether the cause was a genuine parse failure, an image-quality note, or something else, without reading raw `warnings`. | `src/rules.py:32`; reproduced: `CASE-003-DL` REVIEWs solely due to `ROTATED_CAPTURE`/`ROTATED_DOCUMENT` warnings despite 100% field completeness and exact-match extraction against ground truth. |

## Evidence / explainability / audit

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-12 | High | No code path links a `DocumentResult`/`CaseResult` back to the specific image file that was purportedly evidence for the decision (no path, hash, or checksum in `src/models.py`). A decision cannot be proven to correspond to a specific retained image. | `architecture_current.md` §3; `src/models.py` field list. |
| R-13 | Medium | There is no durable audit datastore — decisions are computed fresh on every call and not persisted anywhere (`known_limitations.md:16`). Nothing in `src/` writes decision history; the only "audit trail" is the request/response body itself plus a correlation ID in application logs. | Confirmed no persistence/write code exists outside `data/` read paths in `src/repository.py`. |

## Fraud gaps

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-14 | High | Fraud/authenticity capability is limited to R-09's literal marker match. There is no image forensics, no cross-document consistency check as a fraud signal (R-01/R-02 also function as fraud blind spots, not just identity-quality ones), and no external registry/watchlist check. | `docs/known_limitations.md:8,10,14`; confirmed absent from `src/`. |

## Operational / observability

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-15 | Medium | Logging is one line per HTTP request (method, path, status, correlation ID) with no structured per-decision log (decision, reason codes, case ID) and no distributed tracing. Reconstructing "why did case X get decision Y" from logs alone is not possible; the caller must re-call the API. | `src/app.py:12-17`. |
| R-16 | Medium | No metrics endpoint (`/metrics` or similar) and no SLO instrumentation exist, so the business's own throughput assumption (15 req/sec peak, `docs/business_problem_statement.md:20`) is currently unverifiable in production without external tooling. | Confirmed absent from `src/app.py` route list. |
| R-17 | Low | Health/readiness endpoints exist and were exercised live (`/health/live`, `/health/ready`) but readiness only reports dataset case count and a static `offline_ocr: true` flag — it does not check that `data/` files are structurally valid (that check lives only in `scripts/sanity_check.py`, run out-of-band). | `src/app.py:30-32`; reproduced via `smoke_server.py`. |

## Security / privacy

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-18 | High | No authentication, authorization, rate limiting, or tenant isolation on any `/v1` endpoint. Any caller with network access can enumerate all 6 synthetic cases and verify any document/case. | `src/app.py` route decorators — no auth dependency on any route; confirmed live via unauthenticated `smoke_server.py` calls succeeding. |
| R-19 | Medium | Exception-handling is type-based, not path-based: a bare `ValueError` raised anywhere in the call chain (not just `repository.safe_id`) is mapped to an HTTP 400 with `str(exc)` echoed to the caller (`src/app.py:23-25`). This is low-risk today only because current `ValueError` sources are limited to identifier validation, but it is a latent information-disclosure pattern if a future `ValueError` carries sensitive content. | `src/app.py:23-25`, `src/repository.py:9`. |
| R-20 | Low | Path traversal is blocked (`safe_id` rejects `/`, `\`, `..`) and was confirmed live (`test_path_traversal_blocked`, `POST /v1/documents/verify {"document_id": "../secret"}` → 400). No further filesystem-safety gaps were found in this pass. | `tests/test_api.py:46-47`, `src/repository.py:7-10`. |
| R-21 | Low | No secrets/API keys are present in the repository or required at runtime, consistent with CLAUDE.md rule 7 and `docs/qa_release_report.md`. | `requirements.txt`, `Dockerfile`, `src/` — no credential handling code anywhere. |

## Testing gaps

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-22 | Medium | All 22 tests pass, but none assert on log content, none exercise concurrent/parallel request load, and none test the `config/baseline.json` values actually changing behaviour (because they don't — R-08). Test coverage validates *current wiring*, not the business requirements in `docs/business_problem_statement.md`. | `tests/` directory contents (`test_api.py`, `test_rules.py`, `test_service.py`, `test_release_integrity.py`); reproduced 22/22 pass. |
| R-23 | Low | `docs/qa_release_report.md` states a Docker build was not exercised during packaging ("Docker/Podman daemon was not available"). This assessment also could not build/run the container (no Docker daemon in this environment), so container-level behaviour remains unverified end-to-end. | `docs/qa_release_report.md:23-24`; this session's environment lacked Docker. |

## Deployment limitations

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-24 | Low | The workshop-documented supported Python range is 3.11–3.13 (`WORKSHOP_RUNBOOK.md:7`), but this assessment ran successfully on 3.14.7, one minor version outside the documented/release-tested range. Preflight only fails below 3.11, so nothing blocked the run, but drift beyond the tested range is unmonitored. | `scripts/workshop_preflight.py:25-26`; `python --version` in this session → 3.14.7. |

## Cross-reference to documented operational incidents

See `behavioural_baseline.md` §4 for the full incident-by-incident reproduction table. Two
incidents are directly tied to risks above and are worth surfacing here:

- **INC-117** (surname OCR corruption → "duplicate identity investigation triggered") is
  evidence for **R-01/R-02**: the corruption is reproduced (`CASE-005-NID` field mismatch
  against ground truth), but nothing in current code actually *triggers* an investigation —
  the case silently APPROVEs. The incident's "triggered" outcome must have been a manual/
  operational catch, not software behaviour.
- **INC-139** (tampering "not visible in ordinary parsed fields") is evidence for **R-09**:
  reproduced correctly (`CASE-006` REJECTs), but only because the exact training-data
  marker string is present in the raw OCR text; the detector has no generality beyond that.
