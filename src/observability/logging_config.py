"""Structured (JSON) logging, with the current trace/correlation context injected
into every log line automatically -- a caller does not need to remember to pass
trace_id/correlation_id at each log call site.

This does not weaken src.security.logging_utils' allowlist enforcement for
identity-adjacent fields -- it changes only how a log record is *rendered* (JSON
instead of a plain formatted string), and adds trace context. Never log a raw request
or response body here or anywhere else in this repository (P8/P9: PII minimization in
logs) -- only the same operational-identifier allowlist already enforced upstream.
"""

import json
import logging

from .context import get_current_trace_context

_RESERVED_LOG_RECORD_FIELDS = frozenset(vars(logging.makeLogRecord({})))


class _TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_current_trace_context()
        record.trace_id = ctx.trace_id
        record.correlation_id = ctx.correlation_id
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        # Any extra=... fields passed to the logging call (e.g. by
        # security.logging_utils.log_operational_event or tracing.LoggingSpanExporter)
        # are already pre-validated against an allowlist upstream; surface them as
        # first-class JSON fields rather than burying them in the message string.
        for key, value in vars(record).items():
            if key not in _RESERVED_LOG_RECORD_FIELDS and key not in payload:
                payload[key] = value
        if record.exc_info:
            # Full server-side detail is intentional here (P8: unhandled exceptions are
            # logged in full server-side while the HTTP client only ever sees a generic
            # message) -- this is a server-side log sink, not a client-facing surface.
            payload["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_TraceContextFilter())
    root.addHandler(handler)
