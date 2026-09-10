# SLIs and SLOs — Stage P9

**Read this document's two halves as strictly separate** (P9 requirement 12):
- §1 defines the **SLIs** (what is measured, and how) and reports **currently measured**
  numbers from this repository's own tooling (`python scripts/run_evaluation.py`,
  `GET /metrics`).
- §2 **proposes** SLOs a real deployment might target, derived from
  `docs/business_problem_statement.md`'s stated business volume (~20,000
  applications/day, 15 req/sec peak) — **not** from the measured numbers in §1. The
  measured numbers come from an 11-case curated evaluation set and a synthetic,
  6-case/13-document training dataset; they are not a load test and must never be read
  as evidence that a proposed SLO is currently met or unmet.

## 1. SLIs — definitions and current measurements

### Availability
**Definition**: fraction of `/v1/*` requests that receive an HTTP response (of any
status) rather than the connection failing or the process crashing.
**Measured**: not applicable to measure meaningfully in this single-process, no-load
training environment — every request in every automated check in this repository
(207 pytest tests, `scripts/smoke_server.py`, `scripts/run_evaluation.py`) has received
a response. This is a functional-correctness signal, not an availability measurement
(which requires sustained load and observed uptime over time, both out of scope for a
synthetic training dataset).

### Latency
**Definition**: wall-clock time to compute a `verify_case` result end to end, measured
via `kyc_request_latency_ms` (`GET /metrics`) for real HTTP traffic, or the evaluation
harness's repeated in-process sample for a quick local check.
**Measured** (`var/eval/report.json`, n=30, in-process, no HTTP/ASGI overhead, warm OS
page cache — see the caveat embedded in that report): mean 0.365ms, median 0.342ms,
p95 0.459ms, max 0.478ms. **This measures the deterministic computation only** — no
network, no real OCR/model inference, no concurrent load. It is not a substitute for a
real load test and must not be quoted as evidence of production latency.

### Error rate
**Definition**: fraction of requests resulting in an unexpected exception (5xx) —
`kyc_error_count` / `kyc_request_count` in `/metrics`, or `operations.error_rate` in
the evaluation report (which additionally distinguishes an *expected* exception, such
as an intentionally-malformed adversarial eval case, from a genuinely unexpected one).
**Measured**: 0/11 (0%) unexpected exceptions across the evaluation case set;
`sample_size_warning: true` (n=11 is far below any threshold for a meaningful rate).

### Processing success
**Definition**: fraction of cases that reach a terminal decision (`APPROVE`/`REJECT`)
without requiring `REVIEW` — the same measure as the evaluation harness's
straight-through-processing rate.
**Measured**: 3/6 (50%) on the real synthetic dataset, `sample_size_warning: true`.
This number is an artifact of the training dataset's deliberate scenario mix (half the
6 cases are specifically designed to require review or rejection) — it says nothing
about what fraction of a real applicant population would need review.

## 2. Proposed SLOs (separate from the above; not currently validated)

Derived from `docs/business_problem_statement.md`: ~20,000 applications/day,
2-3 documents/application, 15 verification requests/sec peak, synchronous pre-check
expected to remain responsive under peak load.

| SLI | Proposed SLO | Rationale |
|---|---|---|
| Availability | 99.9% of `/v1/cases/{id}/verify` requests receive a response over a rolling 30-day window | Standard availability target for a synchronous pre-check gating an onboarding flow; not so strict as to require multi-region failover for a first iteration |
| Latency (p95) | ≤ 300ms per case verification, measured end-to-end including real OCR/document-intelligence inference (not the in-process microbenchmark in §1) | At 15 req/sec peak, headroom above the arrival rate is needed even for perfectly parallel processing; 300ms keeps a synchronous caller's UX responsive |
| Error rate | < 0.1% unexpected 5xx responses over any rolling 1-hour window | A KYC pre-check failing open or closed unpredictably is worse than a slow response; this should be tight |
| Processing success (STP rate) | ≥ 70% of cases reach APPROVE/REJECT without manual review, once real-world evidence distributions (not this dataset's deliberately adversarial mix) are used to calibrate `src/decision_policy/` | This is a target for the *policy*, not a target the infrastructure alone can hit — track it, but expect it to move as the policy in `src/decision_policy/engine.py` is tuned, not as a pure ops metric |

**Explicitly not proposed here**: an SLO for identity-resolution match accuracy,
fraud-detection recall, or false-acceptance/false-rejection rate. `docs/data_dictionary.md`'s
evaluation-harness section (P7) already states why: this repository's FAR/FRR figures
measure agreement with a small set of hand-labeled scenario designs, not a calibrated
error rate against any real population — proposing a numeric SLO on top of that would
imply a precision this measurement cannot support (P7 requirement 5/6, restated here
for SLOs specifically).

## 3. Where these numbers come from (reproducibility)

Every measured number in §1 is regenerated by running:
```bash
python scripts/run_evaluation.py   # writes var/eval/report.json
```
or by making a live request and reading `GET /metrics`. Neither requires reading this
document to reproduce — see `docs/operations/runbook.md` for exact commands.
