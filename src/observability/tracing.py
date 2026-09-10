"""A minimal, dependency-free tracing abstraction using OpenTelemetry's own core
concepts (trace_id, span_id, parent_span_id, name, start/end time, attributes,
status) behind a SpanExporter interface -- the same provider-interface pattern used
throughout this repository (DocumentIntelligenceProvider, Authorizer, ...). A real
deployment would implement SpanExporter against the actual OpenTelemetry SDK (or send
spans to an OTLP collector) without changing any start_span() call site.

Attributes on a span are, like log fields (src.security.logging_utils), restricted to
an explicit allowlist of names -- a span must never carry an identity attribute or
raw evidence content (P9 requirement 3, extended from P8's logging discipline to
tracing).
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import time
from uuid import uuid4

from .context import get_current_trace_context

# Mirrors src.security.logging_utils._ALLOWED_FIELDS in spirit: operational
# identifiers, statuses, counts, categories -- never identity attributes or free-text
# evidence content.
ALLOWED_SPAN_ATTRIBUTE_KEYS = frozenset({
    "case_id", "document_id", "review_id", "component", "provider",
    "decision", "status", "outcome", "category", "severity", "count",
    "document_type", "rule_id", "reason_code", "error_type",
    "http_method", "http_path", "http_status",
})


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time: float
    end_time: float | None = None
    attributes: dict = field(default_factory=dict)
    status: str = "OK"  # "OK" or "ERROR", mirroring OTel's StatusCode

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return round((self.end_time - self.start_time) * 1000, 3)


class SpanExporter(ABC):
    @abstractmethod
    def export(self, span: Span) -> None:
        raise NotImplementedError


class InMemorySpanExporter(SpanExporter):
    """Used by tests and by anything that wants to inspect the spans a call produced."""

    def __init__(self):
        self.spans: list[Span] = []

    def export(self, span: Span) -> None:
        self.spans.append(span)

    def clear(self) -> None:
        self.spans.clear()


class LoggingSpanExporter(SpanExporter):
    """Default production exporter: emits one structured log line per completed span
    via the same PII-safe logging path as everything else (src.observability.logging_config)."""

    def __init__(self, logger_name: str = "kyc-v1.trace"):
        import logging
        self._logger = logging.getLogger(logger_name)

    def export(self, span: Span) -> None:
        self._logger.info(
            "span",
            extra={
                "event": "span",
                "span_name": span.name,
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "duration_ms": span.duration_ms,
                "span_status": span.status,
                **span.attributes,
            },
        )


_exporter: SpanExporter = LoggingSpanExporter()
_current_span_id: dict[str, str] = {}  # trace_id -> most recently opened span_id (this process's call stack)


def set_default_exporter(exporter: SpanExporter) -> SpanExporter:
    """Swaps the process-wide exporter (used by tests to capture spans in-memory).
    Returns the previous exporter so callers can restore it."""
    global _exporter
    previous, _exporter = _exporter, exporter
    return previous


def _validate_attributes(attributes: dict) -> dict:
    unknown = set(attributes) - ALLOWED_SPAN_ATTRIBUTE_KEYS
    if unknown:
        raise ValueError(
            f"span attribute(s) {sorted(unknown)} are not in the allowlist -- this looks like it "
            f"might carry identity/evidence content; see ALLOWED_SPAN_ATTRIBUTE_KEYS."
        )
    return attributes


@contextmanager
def start_span(name: str, **attributes):
    ctx = get_current_trace_context()
    parent_span_id = _current_span_id.get(ctx.trace_id)
    span = Span(
        name=name, trace_id=ctx.trace_id, span_id=uuid4().hex[:16],
        parent_span_id=parent_span_id, start_time=time(),
        attributes=_validate_attributes(dict(attributes)),
    )
    _current_span_id[ctx.trace_id] = span.span_id
    try:
        yield span
    except Exception:
        span.status = "ERROR"
        raise
    finally:
        span.end_time = time()
        _current_span_id[ctx.trace_id] = parent_span_id
        _exporter.export(span)
