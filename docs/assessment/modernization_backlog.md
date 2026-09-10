# Modernization Backlog (candidate — not actioned in this pass)

This backlog is derived directly from `risk_register.md` and the incident verification in
`behavioural_baseline.md`. **Nothing in this file has been implemented.** Per the P0
scope, this pass does not build Document Intelligence, identity resolution, fraud models,
new risk scoring, HITL, or production modernization. Items are ordered by the severity of
the risk they address, not by presumed implementation order — sequencing is a design
decision for a later stage, not this one.

Each item names the risk(s) it addresses and the `/v1` compatibility impact it would need
to respect if built, per CLAUDE.md rules 3–4 (preserve API/behaviour unless a requirement
or deficiency justifies an additive change).

## Critical / high severity

1. **Cross-document identity consistency check at case level** (addresses R-01, R-02, and
   the INC-117 gap). Needs: a defined match policy (exact vs fuzzy vs normalized name
   comparison, DOB comparison, and whether `submitted_name`/`submitted_dob` participate),
   new reason code(s) distinct from the current undifferentiated `MANUAL_REVIEW_REQUIRED`,
   and a decision on whether this is additive (new reason codes / new response field) or
   would change existing CASE-005-shaped outcomes — which `docs/scenario_catalog.md`
   already signals as the intended teaching point for this scenario. Any change to
   `CASE-005`'s baseline decision must be treated as a corrected deficiency, not a silent
   behavioural break, and requires updating `data/expected_baseline_outputs/CASE-005.json`
   deliberately with a documented rationale, not as a side effect.
2. **Make `config/baseline.json` the actual runtime source of policy** (addresses R-08).
   Needs: `src/rules.py` and `src/service.py` to load and validate config at startup
   instead of hard-coding literals, with schema validation per CLAUDE.md rule 12
   ("AI/model components may interpret ambiguous evidence but their outputs must be
   schema validated" — applies more broadly to any externally-loaded policy input too).
3. **Replace literal-substring tamper detection with a real signal, or explicitly scope
   it as a placeholder in the API contract** (addresses R-09, R-14). Any real fraud/
   authenticity capability must sit behind an adapter with a deterministic offline
   implementation per CLAUDE.md rule 8, and per rule 10, must not be the sole basis for a
   REJECT without a documented explainability trail (rule 13).
4. **Attach evidence provenance to decisions** (addresses R-12, R-13). Needs: image
   path/hash on `DocumentResult`, and a decision on durable audit persistence (currently
   absent entirely) versus continuing to compute fresh on every call.

## Medium severity

5. **Differentiate REVIEW reason codes by cause** (addresses R-11). Split
   `MANUAL_REVIEW_REQUIRED` into distinguishable codes for genuine parse failure vs
   image-quality marker vs other warning classes, so `docs/engineering_challenge_register.md`
   question 10 ("Are reason codes sufficient for an analyst to reconstruct the decision?")
   has a real answer.
6. **Deduplicate the OCR-quality/rotation warning pairs** (addresses R-07) — cosmetic but
   directly reduces analyst confusion (this is exactly the shape of INC-151, even though
   INC-151 itself wasn't reproducible on the current dataset).
7. **Introduce calibrated confidence instead of raw completeness ratio** (addresses R-10).
   Needs a defined confidence semantic (per-field, not just mandatory-field presence) —
   this is a design question, not a one-line change, and should be scoped before any
   implementation begins.
8. **Structured per-decision logging** (addresses R-15) — log decision, reason codes, and
   case/document ID per verification call, subject to CLAUDE.md rule 16 (no sensitive
   identity attributes in unrestricted logs) — needs a redaction/allowlist decision before
   implementation, not just "log everything."
9. **Metrics/SLO instrumentation** (addresses R-16) to make the 15 req/sec peak-load
   assumption in `docs/business_problem_statement.md` verifiable against reality.

## Lower severity / hygiene

10. **Parser resilience to label-format drift** (addresses R-04, R-06/INC-163) — e.g.
    case-insensitive or fuzzy label matching, with a defined fallback/warning contract so
    a format change degrades gracefully instead of silently dropping a field.
11. **Authentication/authorization/rate limiting on `/v1` routes** (addresses R-18) — scope
    depends on target deployment context; out of scope for a training repository but a
    real blocker for any non-training deployment.
12. **Tighten `ValueError`→400 exception mapping to be path/context-aware** (addresses
    R-19) rather than type-based globally, to avoid accidentally exposing internal error
    text from a future code path.
13. **Track/pin the tested Python range in preflight** (addresses R-24) — either widen the
    documented supported range to include what's actually been validated, or make
    preflight warn (not just silently pass) outside 3.11–3.13.

## Explicitly out of scope for this backlog (per P0 instructions)

Document Intelligence / VLM-based extraction, identity-resolution services, fraud
scoring models, new risk-scoring frameworks, and HITL workflow — all referenced in the
P0 prompt as future-stage work — are intentionally **not** decomposed into backlog items
here. `docs/engineering_challenge_register.md` already frames the open questions those
future stages would need to answer; this backlog only covers what can be inferred from
the current codebase's actual, reproduced behaviour.

## Traceability to the engineering challenge register

Every numbered question in `docs/engineering_challenge_register.md` is answered, at least
provisionally, by evidence already gathered in this assessment:

| Register question | Answered by |
|---|---|
| 1–4 (document handling) | `risk_register.md` R-04–R-07; `behavioural_baseline.md` §4 (INC-101, INC-163) |
| 5–8 (identity consistency) | `behavioural_baseline.md` §3 (CASE-005 walkthrough); `risk_register.md` R-01–R-03 |
| 9–12 (risk and decisioning) | `risk_register.md` R-08, R-10, R-11 |
| 13–16 (operations) | `risk_register.md` R-13, R-15, R-16, R-17; `architecture_current.md` §1 (single correlation ID does span a case's document calls, since `verify_case` calls `verify_document` in-process under one request) |
| 17–20 (security and privacy) | `risk_register.md` R-18–R-21 |
