# Threat Model — Stage P8

Grounded in the actual P0-P7 codebase (file/line references throughout), not generic
boilerplate. Each surface lists what was found, what was changed in this stage
(`src/security/` and its call sites), and what remains a documented, deliberate
residual risk.

## 1. API inputs

| Surface | Finding | Mitigation (this stage) |
|---|---|---|
| `VerifyDocumentRequest.document_id` | Body field, bounded (`min_length=3, max_length=80`) since P0 | Added `model_config = ConfigDict(extra='forbid')` — an unexpected extra JSON field is now rejected (422) rather than silently ignored (`src/models.py`). |
| `ReviewTransitionRequest` | Bounded field lengths since P6 | Same `extra='forbid'` hardening (`src/review/models.py`). |
| `case_id` / `review_id` path parameters | Previously plain `str`, unbounded length, no format constraint at the route layer — validation only happened downstream in `repository.safe_id`/SQL lookups | Every path parameter now goes through `Path(min_length=1, max_length=80, pattern=IDENTIFIER_PATTERN_STR)` (`src/app.py:_identifier_path`) — malformed/oversized identifiers are rejected (422) before any handler code, file I/O, or SQL query runs. |
| `status` query parameter on `GET /v1/reviews` | Pydantic enum-typed (`ReviewStatus \| None`) already — any non-enum value is rejected (422) | Unchanged; already correct. |

## 2. Document identifiers / file access

**Finding**: `src/repository.py:safe_id` (P0) used a **denylist** — reject `/`, `\`,
`..`. A denylist is only as good as the list of things someone thought to block; it
does not defend against null bytes, control characters, unicode homoglyphs, or simply
a very long string used for resource exhaustion.

**Mitigation**: `src/security/identifiers.py:validate_identifier` replaces this with
an **allowlist** — `^[A-Za-z][A-Za-z0-9_-]{0,79}$` — safe by construction against every
character-based traversal/injection trick, not just the ones already known.
`repository.safe_id` now delegates to it (verified behavior-neutral: full regression
suite passed unchanged before any other change was made — see the P8 session's
implementation log). `tests/test_security.py::test_identifier_allowlist_rejects_every_malformed_id`
exercises null bytes, path separators, absolute paths, unicode, leading-digit/hyphen,
and oversized-length cases directly.

**Residual risk**: `repository.py` never opens a file outside `DATA/` even before this
change (path is always `DATA/folder/f'{ident}.json'`), so there was no live traversal
vulnerability — this hardening is defense-in-depth against future code that might
compose paths less carefully, not a fix for an exploitable bug found in this pass.

## 3. File access / resource bounds

**Finding**: `load_json`/`load_sidecar` read entire files into memory with no size
cap. This repository's real fixtures are a few KB; a corrupted or hostile file far
larger than that would be read in full before any validation occurred.

**Mitigation**: `src/repository.py:_read_bounded` refuses to read a file over
`MAX_FILE_BYTES` (1 MB), raising `ValueError` (mapped to `400`) before the content is
loaded. Verified behavior-neutral for the real dataset; tested directly
(`tests/test_security.py::test_repository_refuses_to_read_a_file_beyond_the_size_bound`).

## 4. OCR/model output (malformed documents / provider payloads)

Largely already addressed structurally in P1/P3/P4, reaffirmed and tested here rather
than re-implemented:
- `src/document_intelligence/provider.py:extract_evidence` rejects any provider return
  value that is not a schema-validated `DocumentEvidence` (`ProviderContractError`) —
  P1, tested in `tests/test_document_intelligence.py`.
- Every Pydantic model in this repository validates its own fields at construction
  time; a provider cannot produce an out-of-range confidence, an invalid enum value, or
  a malformed nested structure without an immediate `ValidationError`.
- `src/evidence_validation/checks.py` never treats a malformed/unparseable date as
  valid (P3) — a failure to parse is `FAIL`/`NOT_APPLICABLE`, never a fabricated `PASS`.
- **New in this stage**: `src/security/redaction.py:sanitize_for_display` is applied
  in `src/review/summary.py` — document-derived field values reaching the
  analyst-facing reviewer summary can no longer inject control characters/newlines
  into that narrative (see §12).

## 5. Persistence

**Finding**: P6 introduced the first durable PII-at-rest in this repository
(`var/review_store.sqlite3` — `evidence_summary`, `discrepancies`, `fraud_signals` may
embed real names/dates). Before P6, the service was fully stateless (computed fresh on
every call, nothing written to disk).

**Mitigation / findings this stage**:
- All SQL in `src/review/store.py` is parameterized (`?` placeholders) — no string
  interpolation into a query anywhere. Verified not just by inspection but by test:
  `tests/test_security.py::test_review_store_is_safe_against_sql_metacharacters_in_free_text_fields`
  stores a `'); DROP TABLE review_cases; --`-style payload as `analyst_action`/
  `rationale`/`correction` and confirms it is retrieved verbatim as data, the table
  survives, and no other row is affected.
- Added `ReviewStore.purge_review()` — a hard-delete primitive for both the review row
  and its full audit trail (§17, retention/deletion boundary).
- No encryption-at-rest is implemented for the SQLite file — see §17 and
  `docs/security/privacy_data_flow.md` for why this is a documented, not silently
  omitted, boundary.

## 6. Logs

**Finding**: `src/app.py`'s correlation middleware logs `method`, `path`, `status`,
`correlation_id` only — confirmed by direct inspection this was already true, and nothing
else in `src/` called `logging` before this stage.

**Mitigation**: `src/security/logging_utils.py:log_operational_event` provides an
allowlist-of-field-**names** logging helper for any future call site — passing a field
name not on the allowlist (e.g. `full_name`) raises immediately rather than silently
logging it, making "accidentally logged PII" a loud error instead of a silent leak.
`tests/test_security.py::test_request_logging_never_includes_identity_attribute_values`
asserts, by actually capturing log output during a real request, that no known
synthetic PII value appears in it. See §20 for why this matters even though the
dataset is synthetic.

## 7. Review endpoints

Addressed together with §9/§10 below (authentication/authorization + rate limiting)
since the review subsystem is the concrete surface those requirements are applied to.

## 8. Configuration

- `config/baseline.json`, `config/security.json` are loaded via small, dependency-free
  leaf modules (`src/policy.py`, `src/security/auth.py`) that fail gracefully (fall
  back to built-in defaults) if the file is missing/malformed — the service never
  crashes at startup due to a bad config file, consistent with "fail safely."
- `config/security.json` is explicitly labeled as workshop-only, non-secret, and
  overridable via the `REVIEWER_API_KEYS` environment variable (§15).

## 9. Dependencies

`pip check` (fully offline — verifies installed package compatibility, no network
call) reports no broken requirements. `pip-audit`/`safety` (CVE-database-backed
vulnerability scanners) are not installed in this environment and were not installed
for this check: a genuine vulnerability scan needs network access to a CVE feed, which
would violate this repository's "runs fully offline" constraint if made a hard
requirement of the checks in `scripts/`. This is a documented, not silently omitted,
gap — see §19 in `docs/data_dictionary.md`'s evaluation-harness-adjacent security
section for the full account of what was and wasn't checked. `requirements.txt` pins
every dependency to an exact version; `Dockerfile` does not pin the base image by
digest (`python:3.12-slim` — a tag, not a digest) — a documented supply-chain
hardening recommendation for a real deployment, not implemented here since verifying a
specific digest requires registry access this offline environment doesn't exercise.

## 10. Authentication / Authorization (requirements 9-10)

**Finding**: every endpoint in this service was unauthenticated through P7 (P0's R-18).

**Mitigation**: `src/security/auth.py` introduces an `Authorizer` interface with one
implementation, `StaticWorkshopAuthorizer` — a deterministic, offline, config/env-driven
static credential set. Applied to **every** `/v1/reviews*` and `/v1/cases/{id}/reviews`
endpoint (read and mutate) via `Depends(require_reviewer)` in `src/app.py`: a missing or
invalid `X-API-Key` header returns `401`; a valid credential lacking the `reviewer` role
returns `403`.

**Deliberate, documented scope boundary**: `/v1/documents/verify` and
`/v1/cases/{id}/verify` remain unauthenticated in this stage. Extending auth to those
endpoints is a natural next step but was judged disproportionate for this stage's blast
radius — it would require updating the calling convention of essentially every test in
`tests/` written across P0-P7 (100+ tests), where the review subsystem's auth change
only required updating the ~10 tests that call review endpoints directly. This is an
explicit, acknowledged residual risk, not an oversight.

## 11. Rate / resource limits (requirement 11)

`src/security/limits.py:RateLimiter` — an in-memory, single-process, fixed-window
counter, explicitly documented as a workshop-appropriate mechanism (not a
distributed/production rate limiter) with a clean interface (`check(key)`) a real
deployment would back with a shared store. Applied to `POST
/v1/reviews/{id}/transitions` (20 requests/60s per authenticated subject) — the
concrete demonstration point requirement 11 asks for ("clearly testable integration
points"). Exceeding it returns `429`.

## 12. Model/Document-Intelligence boundary: prompt injection, embedded instructions, schema bypass

**No LLM exists anywhere in this repository** (confirmed since P0, re-confirmed in
every subsequent stage's report). There is no "prompt" for injected document text to
hijack. The relevant, concrete risk in a system with no LLM is different but related:
**document-derived content must never be interpreted as anything other than data** —
not as a parsing directive, not as a log-format string, not as a narrative instruction.

Findings and mitigations:
- The line-prefix parser (`src/parser.py`) matches on exact label prefixes only; it
  has no `eval`/`exec`/template-interpolation path that could turn field content into
  code. Confirmed by inspection — no such construct exists anywhere in `src/`.
- All SQL access is parameterized (§5) — a crafted field value cannot become a SQL
  instruction even where it eventually reaches persistence via a review correction.
- **New in this stage**: `sanitize_for_display` (§4) strips control characters
  (including newlines) from document-derived values before they reach the
  analyst-facing reviewer summary — a crafted field value containing
  `"Name\n2026-01-01 FAKE INFO admin_override=true"` can no longer forge what looks
  like a second log/narrative line. Tested directly:
  `tests/test_security.py::test_reviewer_summary_never_contains_raw_control_characters`.
- **Schema bypass**: `model_config = ConfigDict(extra='forbid')` on both user-facing
  request models (§1) rejects unexpected request shapes outright. Provider outputs are
  already schema-validated at construction (§4).
- **Residual, documented scope**: `sanitize_for_display` is applied at one high-leverage
  point (the reviewer summary) in this stage, not retroactively at every explanation-
  string call site across `evidence_validation`/`fraud_signals`/`decision_policy`
  (dozens of f-strings across 4 packages). Those strings are returned in API responses
  intended to carry evidence content (a legitimate use), not logged, so the log-injection
  vector specifically is closed; a future pass could apply the same sanitizer more
  broadly for defense-in-depth. This scope choice is deliberate and documented, not
  silently incomplete.

## 13. The rule: document content is DATA, never trusted system instruction

Stated explicitly, here and in code:
- `src/security/redaction.py`'s module docstring states this rule directly.
- `src/parser.py`, `src/document_intelligence/sidecar_provider.py`, and every rules/
  validation/fraud-signal module treat extracted field values purely as string data
  compared against patterns/dates/other strings — never executed, never used to select
  code paths, never trusted as configuration.
- `src/fraud_signals/provider.py`'s `DocumentForensicsProvider` docstring (P4) already
  states the adjacent rule for any future forensics provider: "never an LLM's free-text
  assertion that a document 'looks fraudulent'" — signals are evidence, never verdicts.
- `src/review/summary.py`'s `ReviewSummaryProvider` docstring (P6) states the same
  constraint for any future LLM-backed summarizer: ground every statement in supplied
  evidence, never invent facts.

## 14. Validate every AI/provider response before use

Already satisfied structurally since P1 (§4) — reaffirmed, not re-implemented, in this
stage. `extract_evidence()` enforces the `DocumentEvidence` contract; Pydantic enforces
every other model's contract at construction. No response from any provider interface
in this codebase (`DocumentIntelligenceProvider`, `DocumentForensicsProvider`,
`ReviewSummaryProvider`) is ever used before it has passed schema validation.

## 15. Secrets / configuration hygiene (requirement 15)

- `config/security.json` ships a clearly-labeled, non-secret workshop default
  (`"workshop-reviewer-key"`) with an explicit comment stating it must not be reused in
  a real deployment.
- `REVIEWER_API_KEYS` (comma-separated) environment variable, when set, **replaces**
  the config file's credential set entirely — the intended override point so a real
  deployment's credential never has to be committed to source control.
- No other secret-shaped value exists in this repository (`requirements.txt`,
  `Dockerfile`, `.env` is gitignored though unused today).
- `var/` (containing the SQLite review database) is gitignored — durable PII-bearing
  state is never committed.

## Summary of what changed vs. what is documented residual risk

| Area | Changed in P8 | Documented residual (not implemented) |
|---|---|---|
| Identifiers | Denylist → allowlist | — |
| File reads | Unbounded → 1MB cap | — |
| Review endpoints | Open → authenticated (`reviewer` role) | Core verify endpoints remain open |
| Review mutations | Unlimited → rate-limited | Single-process only, not distributed |
| Request schemas | Permissive → `extra='forbid'` | — |
| Error responses | Framework default → centralized, sanitized | — |
| Reviewer summary | Unsanitized field values → control-char-stripped | Not retrofitted to every explanation string elsewhere |
| Review persistence | No deletion capability → `purge_review()` primitive | No scheduled/automatic purge; no API endpoint exposes it yet |
| Data at rest | — | No encryption at rest for the SQLite file |
| Dependencies | `pip check` run and documented | No CVE-database-backed scan (network-dependent, out of the offline constraint) |
| Docker base image | — | Not pinned by digest |
