# Local Operational Runbook — Stage P9

Concrete, copy-pasteable procedures for this locally-runnable service. Every command
below was actually run against this repository while writing this document.

## Start the service

```bash
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000
```

Logs are structured JSON on stdout, one line per event (P9 requirement 2):
```json
{"timestamp": "...", "level": "INFO", "logger": "kyc-v1", "message": "request", "trace_id": "...", "correlation_id": "...", "event": "http_request", "path": "/v1/cases/CASE-005/verify", "method": "POST", "http_status": 200, "latency_ms": 2.099}
```

## Diagnostic 1 — "Is the service healthy?"

```bash
curl -s http://127.0.0.1:8000/health/live    # process is up
curl -s http://127.0.0.1:8000/health/ready   # dependencies are actually reachable
```

`/health/ready` returns a `checks` object, not just a boolean — read it, don't just
check the status code:
```json
{"status": "ready", "offline_ocr": true, "dataset_cases": 6,
 "checks": {"dataset": "ok", "review_store": "ok", "auth_config": "ok"}}
```
If `checks.auth_config` says `"degraded: no reviewer credentials configured"`, every
`/v1/reviews*` request will 401 regardless of what credential is presented — fix
`config/security.json` or `REVIEWER_API_KEYS` before escalating an auth complaint.
If `checks.review_store` shows an `error:`, the SQLite file at `var/review_store.sqlite3`
(or `$REVIEW_DB_PATH`) is not writable/reachable — check disk space and permissions.

## Diagnostic 2 — "What is current traffic/error/decision volume?"

```bash
curl -s http://127.0.0.1:8000/metrics
```

Look for, in order of triage priority:
- `kyc_error_count{...}` — any nonzero label combination is a path currently erroring.
- `kyc_provider_failures_total` — nonzero means the document-intelligence or fraud
  forensics provider contract was violated; see `src/document_intelligence/provider.py`'s
  `ProviderContractError`.
- `kyc_decisions_total{decision="REJECT"}` vs `{decision="APPROVE"}` — a sudden shift
  in this ratio without a known cause (a deployed policy change, a new document
  format) is worth a decision-lineage-based investigation (Diagnostic 3).
- `kyc_request_latency_ms` (the `quantile="p95"` line) — compare against the proposed
  SLO in `docs/operations/slis_slos.md` §2 (not the measured baseline in §1, which is
  a different, non-representative workload).

## Diagnostic 3 — "Reconstruct exactly what happened and why for one case"

This is the success criterion for this stage: do this **without reading source code**.

1. Get the correlation ID for the request in question (from the client's logs, or the
   `x-correlation-id`/`x-trace-id` response header — they are the same value for a
   single request, see `src/observability/context.py`).
2. Grep the service's structured logs for that trace_id:
   ```bash
   grep '"trace_id": "<trace-id>"' service.log | python3 -m json.tool --json-lines
   ```
   This returns every span emitted for that request, in the order they completed,
   each showing `span_name`, `duration_ms`, and `span_status` — the full pipeline
   trace: `http.request` → `service.verify_case` → `service.verify_document` (×N) →
   `document_intelligence.extract` → `evidence_validation.validate_document` →
   `fraud_signals.assess_document` → `identity_resolution.resolve` →
   `evidence_validation.validate_case` → `fraud_signals.assess_case` →
   `decision_policy.assess` (and `review.open` if a review was created).
3. Re-run the same case to get the full `CaseResult`, including `decision_lineage`:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/v1/cases/CASE-005/verify | python3 -m json.tool
   ```
   Read `decision_lineage` directly:
   ```json
   {
     "trace_id": "...",
     "case_id": "CASE-005",
     "decision": "REVIEW",
     "policy_version": "1.0.0",
     "component_versions": {
       "decision_policy": "1.0.0",
       "evidence_validation": "1.0.0",
       "identity_resolution": "1.0.0 (fuzzy_threshold=0.75)",
       "document_intelligence_provider": "deterministic_sidecar_ocr",
       "fraud_forensics_provider": "deterministic_marker_forensics"
     },
     "risk_factor_summary": [
       "CASE-005:full_name:CONFLICT (identity_conflict, HIGH)",
       "FRAUD:CASE-005:full_name:CASE-005-PASSPORT:CASE-005-NID (fraud_signal, MEDIUM)"
     ],
     "evidence_reference_count": 2
   }
   ```
   This alone answers: which policy version decided this, which exact version of
   every component contributed, and which specific risk factors drove the outcome —
   the decision lineage (P9 requirement 9). For the full detail behind each factor,
   the same response's `risk_assessment.risk_factors`, `identity_resolution`,
   `validation`, and `fraud_assessment` fields carry the complete evidence trail
   each `decision_lineage` entry summarizes.
4. If the case is under human review, its `ReviewCase.reviewer_summary` (via
   `GET /v1/reviews/{review_id}`, with a reviewer credential) gives the same story in
   prose, grounded only in this same evidence (`src/review/summary.py`).

## Diagnostic 4 — "An extraction/validation/fraud/identity component seems wrong"

Each pipeline stage emits its own span (Diagnostic 3) and its own metric counter
(Diagnostic 2: `kyc_extraction_failures_total`, `kyc_validation_failures_total`,
`kyc_identity_conflicts_total`, `kyc_fraud_referrals_total`) labeled by the relevant
category — filter `/metrics` or the structured logs by that label to isolate which
document type / rule / attribute is implicated before looking at any single case.

## Diagnostic 5 — "Run the evaluation harness locally"

```bash
python scripts/run_evaluation.py
```
Writes `var/eval/report.json` and prints a pass/fail summary against the release
gates defined in `eval/gates.py`. Use this after any change to `src/decision_policy/`,
`src/identity_resolution/`, `src/evidence_validation/`, or `src/fraud_signals/` to
check for a regression before it reaches a real case.

## Diagnostic 6 — "A reviewer says they can't act on a case"

```bash
curl -s -X POST http://127.0.0.1:8000/v1/cases/CASE-005/reviews \
  -H "X-API-Key: workshop-reviewer-key"
```
- `401` → credential missing/invalid — check `config/security.json`/`REVIEWER_API_KEYS`.
- `403` → credential valid but lacks the `reviewer` role.
- `409` on open → the case's `decision` is not `REVIEW` (only `REVIEW` cases may open
  an ordinary review — see `docs/security/threat_model.md` §10).
- `409` on a transition → an invalid state transition was attempted; `GET
  /v1/reviews/{review_id}/history` shows the review's actual current state and full
  audit trail.
- `429` → the reviewer has exceeded 20 transitions/60s (`src/security/limits.py`).

## Diagnostic 7 — "Full local pre-flight before trusting any of the above"

```bash
python scripts/workshop_preflight.py
python scripts/sanity_check.py
python -m pytest -q
python scripts/smoke_server.py
python scripts/run_evaluation.py
```
All five must exit `0`. If any fails, the numbers/traces from Diagnostics 1-6 are not
trustworthy until it's fixed.
