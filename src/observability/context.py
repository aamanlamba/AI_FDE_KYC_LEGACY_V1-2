"""One trace/correlation context propagated across every component in the pipeline
(API -> document processing -> extraction -> identity resolution -> validation ->
fraud -> policy -> HITL creation) without changing any of those components' function
signatures.

Uses contextvars (stdlib) rather than threading a trace_id parameter through every
call in src.service/src.document_intelligence/src.identity_resolution/
src.evidence_validation/src.fraud_signals/src.decision_policy/src.review -- the same
mechanism OpenTelemetry's own SDK uses for context propagation within one process.
This is the "OpenTelemetry-compatible abstraction" referenced in P9 requirement 7:
same core concepts (trace_id, span_id, parent_span_id), no dependency on the actual
opentelemetry-api package.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    correlation_id: str


_current: ContextVar[TraceContext | None] = ContextVar("kyc_trace_context", default=None)


def new_trace_id() -> str:
    return uuid4().hex


def get_current_trace_context() -> TraceContext:
    """Always returns a context -- callers outside an HTTP request (scripts, the eval
    harness, direct Python API use) still get a fresh, valid trace_id rather than a
    None that every call site would need to guard against."""
    ctx = _current.get()
    if ctx is None:
        return TraceContext(trace_id=new_trace_id(), correlation_id=new_trace_id())
    return ctx


@contextmanager
def bind_trace_context(*, trace_id: str | None = None, correlation_id: str | None = None):
    """Binds a TraceContext for the duration of the with-block. src.app's correlation
    middleware calls this once per HTTP request, reusing the x-correlation-id header
    as both the correlation_id and the trace_id (there is one process, one request,
    one trace -- unifying them keeps the operator-facing story simple: the header a
    caller already sees IS the trace to look up)."""
    ctx = TraceContext(
        trace_id=trace_id or new_trace_id(),
        correlation_id=correlation_id or trace_id or new_trace_id(),
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
