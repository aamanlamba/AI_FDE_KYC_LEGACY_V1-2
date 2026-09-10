# ADR-004: `contextvars` for trace propagation, not a threaded parameter

**Status**: Accepted (P9)

## Context
P9 needed one trace/correlation context propagated across API → document
intelligence → identity resolution → validation → fraud → policy → HITL creation —
seven packages built independently across P1-P6, none of which had a `trace_id`
parameter in their public functions.

## Decision
Use `contextvars.ContextVar` (`src/observability/context.py`) to hold the current
`TraceContext`, bound once per HTTP request (or explicitly via `bind_trace_context()`
in tests/scripts), and read implicitly by `start_span()` and the logging filter.

## Consequences
- Zero function-signature changes across `document_intelligence`, `identity_resolution`,
  `evidence_validation`, `fraud_signals`, `decision_policy`, or `review` — instrumentation
  was added entirely at the existing call sites in `src/service.py`/`src/review/workflow.py`.
- `get_current_trace_context()` always returns a usable context even outside an HTTP
  request (scripts, the eval harness, direct Python API use get a fresh trace_id
  automatically) — no caller has to guard against "no active trace."
- Trade-off: this is standard-library, in-process context propagation, not a
  drop-in OpenTelemetry SDK. A real deployment wanting distributed tracing across
  multiple processes/services would still need to adopt an actual OTel SDK or
  propagate a trace header across process boundaries — this abstraction's `Span`/
  `SpanExporter` shapes were deliberately chosen to make that swap straightforward
  (same core concepts: trace_id, span_id, parent_span_id), not to avoid it forever.
- A real concurrency bug was caught by this design's own review (P10): the span-stack
  dict keyed by trace_id was never pruned, an unbounded per-request memory leak under
  sustained traffic. Fixed by deleting the entry once a trace's root span completes.
