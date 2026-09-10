# Behavioural Baseline — Repo 1.0

All results below were produced by actually executing the service against the shipped
synthetic dataset in this session (fresh `.venv`, `requirements.txt` pinned versions,
Python 3.14.7). Machine-readable form: `baseline_results.json` in this directory.

## 1. Case-level results (via `scripts/run_demo.py` and `verify_case`)

| Case | Scenario | Decision | Reason codes | Matches `data/expected_baseline_outputs/`? |
|---|---|---|---|---|
| CASE-001 | clean | APPROVE | BASELINE_RULES_PASSED | Yes (byte-for-byte, `test_release_integrity.py`) |
| CASE-002 | noisy_scan | REVIEW | MANUAL_REVIEW_REQUIRED | Yes |
| CASE-003 | rotated_document | REVIEW | BASELINE_RULES_PASSED, MANUAL_REVIEW_REQUIRED | Yes |
| CASE-004 | expired_passport | REJECT | BASELINE_RULES_PASSED, DOCUMENT_EXPIRED | Yes |
| CASE-005 | name_variation_ocr_error | **APPROVE** | BASELINE_RULES_PASSED | Yes — see § 3 |
| CASE-006 | suspected_tampering | REJECT | BASELINE_RULES_PASSED, SUSPECTED_TAMPERING | Yes |

All 6 case-level results match the committed `data/expected_baseline_outputs/*.json`
exactly (verified both via `pytest`'s `test_expected_case_outputs_are_current_regression_snapshots`
and independently via a fresh `verify_case()` call per case in this session).

## 2. Document-level extraction results (13 documents, all cases)

Field-match is computed against `data/ground_truth/<doc>.json` for the 7 comparable
fields (`full_name`, `date_of_birth`, `document_number`, `issue_date`, `expiry_date`,
`address`, `nationality`; a field is skipped if ground truth has it as `null`).
Mandatory-field completeness is the service's own metric (`src/rules.py:12-13`, 4-field
basis).

| Document | Scenario | Ground-truth field match | Mandatory completeness | Decision | Warnings |
|---|---|---|---|---|---|
| CASE-001-PASSPORT | clean | 6/6 | 1.0 | APPROVE | — |
| CASE-001-NID | clean | 6/6 | 1.0 | APPROVE | — |
| CASE-001-DL | clean | 6/6 | 1.0 | APPROVE | — |
| CASE-002-PASSPORT | noisy_scan | 6/6 | 1.0 | REVIEW | DEGRADED_OCR_QUALITY, OCR_QUALITY_DEGRADED |
| CASE-002-NID | noisy_scan | 6/6 | 1.0 | REVIEW | DEGRADED_OCR_QUALITY, OCR_QUALITY_DEGRADED |
| CASE-003-DL | rotated | 6/6 | 1.0 | REVIEW | ROTATED_CAPTURE, ROTATED_DOCUMENT |
| CASE-003-PASSPORT | rotated | 6/6 | 1.0 | APPROVE | — |
| CASE-004-PASSPORT | expired | 6/6 | 1.0 | REJECT | — |
| CASE-004-NID | expired (sibling, itself unexpired) | 6/6 | 1.0 | APPROVE | — |
| CASE-005-PASSPORT | name_variation | 6/6 | 1.0 | APPROVE | — |
| CASE-005-NID | name_variation + ocr_error | **5/6** | 1.0 | APPROVE | — |
| CASE-006-PASSPORT | tampering | 6/6 | 1.0 | REJECT | — |
| CASE-006-DL | tampering (sibling, itself clean) | 6/6 | 1.0 | APPROVE | — |

**Field-level mismatch detail (the one extraction inaccuracy in the whole dataset):**
`CASE-005-NID` ground truth `full_name = "Mohammad Rehman"`, parsed `full_name =
"Moharnmad Rehrnan"` — the sidecar deliberately encodes OCR-style corruption
(`m`→`rn` substitution). This is extracted *faithfully* by the parser (the parser is not
at fault — it correctly captured whatever text was in the sidecar); the corruption is
injected upstream of parsing, in the sidecar itself, to simulate real OCR noise.

**Observation on `CASE-004` (expired scenario):** only the passport document is actually
expired (`expiry_date: 2025-04-30`, before the frozen reference date `2026-09-09`); the
sibling national ID (`CASE-004-NID`, `expiry_date: 2034-01-01`) independently APPROVEs.
The case-level REJECT is correct here only because `max(rank)` picks up the passport's
REJECT — this is the one case in the dataset where the "worst document wins" aggregation
policy produces the compliance-correct outcome. `CASE-005` is the case in the dataset
where the same aggregation policy (silently) produces a questionable outcome, because
none of its documents individually fail.

## 3. Headline scenario in detail — CASE-005

```
Application (data/applications/CASE-005.json):
  submitted_name: "Mohammad Rehman"
  submitted_dob:  "1992-12-08"

CASE-005-PASSPORT ground truth / OCR (clean):
  full_name: "Mohammed Rahman"      <- differs from submitted_name already (legitimate
                                        transliteration variance between documents,
                                        per docs/scenario_catalog.md's stated intent)
  date_of_birth: "1992-12-08"

CASE-005-NID ground truth:
  full_name: "Mohammad Rehman"       <- matches submitted_name
  OCR sidecar (corrupted): "Moharnmad Rehrnan"
  date_of_birth: "1992-12-08"
```

Three different spellings of the same underlying name appear across submitted data,
passport, and (corrupted) national-ID OCR. DOB is consistent across all three. Under the
current implementation:
- Each document individually reaches 100% mandatory-field completeness and passes all
  rules → `APPROVE`.
- `verify_case` never reads `submitted_name`, never compares `full_name` across
  documents, never compares DOB across documents (`src/service.py:16-22`).
- Case decision: **APPROVE**, reason code `BASELINE_RULES_PASSED`, with the standing
  `limitation_notice` string attached to every case result regardless of scenario.

This is the concrete, reproduced instance of `docs/engineering_challenge_register.md`
questions 5–8 and 15/8 ("Can inconsistent evidence be incorrectly aggregated into a
case-level decision?" — yes, confirmed).

## 4. Operational incidents verified against the implementation

| Ref | Documented symptom | Reproduction attempt | Result |
|---|---|---|---|
| INC-101 | Rotated document produced *incomplete extraction* | Ran `CASE-003-DL` (the rotated document) | **Partially reproducible.** The document is flagged and forced to REVIEW (`ROTATED_CAPTURE`/`ROTATED_DOCUMENT` warnings), matching the operational outcome (referred to manual review). But extraction itself is *not* incomplete: field-match is 6/6 against ground truth and mandatory completeness is 1.0. The system detects rotation only via a literal text marker in the sidecar, not via any actual degradation of extracted fields — current synthetic data does not exercise a true extraction-completeness failure from rotation. |
| INC-117 | OCR corruption changed surname characters → duplicate identity investigation *triggered* | Ran `CASE-005-NID` vs ground truth, then `verify_case('CASE-005')` | **Corruption reproduced** (`Moharnmad Rehrnan` vs ground truth `Mohammad Rehman`). **Investigation-trigger not reproduced**: the case-level code has no mechanism that would trigger any investigation — it APPROVEs. The incident's "triggered" outcome does not correspond to any code path in `src/`; it must reflect a manual/operational catch outside this system, or a gap that has since regressed to silent APPROVE. |
| INC-124 | Expired document required consistent rejection | Ran `verify_case('CASE-004')` | **Fully reproduced.** REJECT with `DOCUMENT_EXPIRED`, deterministically, based on the frozen `REFERENCE_DATE`. |
| INC-139 | Suspicious text alteration not visible in ordinary parsed fields → manual fraud investigation required | Ran `verify_case('CASE-006')` | **Fully reproduced**, and the mechanism matches the symptom exactly: the tamper marker (`SECURITY NOTE: ALTERED_TEXT_REGION_DETECTED`) is deliberately excluded from both `parsed_fields` and `UNPARSED_LINE` warnings (`src/parser.py:15`), so it is genuinely invisible anywhere except the REJECT decision and reason code itself — an analyst reading only `parsed_fields` would not see why. |
| INC-151 | Similar documents produced different completeness scores | Computed `completeness()` for all 13 documents | **Not reproducible on current dataset.** Every one of the 13 shipped documents scores `1.0`; no pair of "similar" documents in this dataset diverges in completeness. Consistent with the incident's own status field (`Under investigation`) — this assessment did not find new evidence either way, only confirmed the current dataset doesn't exercise it. |
| INC-163 | Parser required code change after upstream format variation → release delay | Structural review of `src/parser.py` | **Structurally confirmed as an ongoing design property**, not reproducible as a single test run. `PREFIXES` (parser) and `PATTERNS` (rules) are hard-coded dicts; any new label wording or document type requires editing both and redeploying — there is no data-driven or configurable parsing path today. |

## 5. Test inventory (22 tests, all passing)

| File | Tests | Purpose |
|---|---|---|
| `tests/test_api.py` | 10 | HTTP-level contract: health, cases list, verify endpoints, 404s, path-traversal block, request validation, correlation-ID passthrough |
| `tests/test_rules.py` | 3 | Pure rules-engine unit tests: approve/expire/tamper |
| `tests/test_service.py` | 6 | Case-level scenario outcomes for all 6 scenarios, including the explicit "critical weakness" assertion for CASE-005 |
| `tests/test_release_integrity.py` | 2 | Every referenced document executes end-to-end and its image decodes; every case's live output matches the committed expected-baseline snapshot exactly |
| `scripts/sanity_check.py` (not pytest, but part of the gate) | — | Deep structural/dataset validation: file cross-referencing, schema completeness, orphan detection, expected-output drift detection, future-state phrase leakage scan |

Total automated coverage confirmed: **22 pytest tests + 1 sanity script + 1 preflight
script + 1 live-server smoke script, all green** in this environment on 2026-09-10.

## 6. Timing (in-process microbenchmark — see caveat in `brownfield_baseline.md` §5)

| Operation | Volume | Wall time | Rate |
|---|---|---|---|
| `verify_document` | 500 calls (cycling all 13 docs) | 0.0219s | ~22,780 calls/sec |
| `verify_case` | 100 calls (cycling all 6 cases) | 0.0344s | ~2,911 calls/sec |
| `sanity_check.py` (full dataset validation) | 1 run | 2.18s | — |
| `pytest -q` (22 tests) | 1 run | 0.30s | — |
| `smoke_server.py` (real Uvicorn boot + HTTP round trips) | 1 run | 2.51s | — |

These numbers characterize the deterministic code path only (file reads from local disk,
regex, dict lookups) — they are not a proxy for real-OCR or real-network latency and
should not be used to validate the 15 req/sec production peak-load assumption.
