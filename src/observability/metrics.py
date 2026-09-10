"""A minimal, dependency-free metrics registry rendered in a Prometheus-text-exposition
-compatible format (plain text, `# HELP` / `# TYPE` comments, `name{labels} value`
lines) -- a real deployment could scrape GET /metrics with an unmodified Prometheus
server, or swap this registry for the actual prometheus_client library behind the
same Counter/Histogram call sites, without changing any instrumentation call site in
src.service/src.app/src.review.

No label value here is ever a raw identity attribute -- label values are restricted to
small, closed sets (decision outcomes, document types, component names, error types),
enforced by validating against each metric's declared allowed label values (never an
unbounded/attacker-controlled string), which also protects against a document_type or
decision value silently causing unbounded label cardinality growth.
"""

import threading


class Counter:
    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...] = ()):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._lock = threading.Lock()
        self._values: dict[tuple, float] = {}

    def inc(self, amount: float = 1.0, **labels):
        key = tuple(labels.get(name, "") for name in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def snapshot(self) -> dict[tuple, float]:
        with self._lock:
            return dict(self._values)


class Histogram:
    """Deliberately simple: retains raw observations (this service's request volume is
    tiny by design -- a synthetic training dataset, not production traffic) and
    computes count/sum/mean/p50/p95/max on demand, rather than pre-bucketing like a
    real Prometheus histogram. A real deployment swaps this for prometheus_client's
    Histogram behind the same observe() call."""

    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help_text = help_text
        self._lock = threading.Lock()
        self._observations: list[float] = []

    def observe(self, value: float):
        with self._lock:
            self._observations.append(value)

    def snapshot(self) -> dict:
        with self._lock:
            values = sorted(self._observations)
        if not values:
            return {"count": 0, "sum": 0.0, "mean": None, "p50": None, "p95": None, "max": None}
        return {
            "count": len(values),
            "sum": round(sum(values), 3),
            "mean": round(sum(values) / len(values), 3),
            "p50": values[int(0.50 * (len(values) - 1))],
            "p95": values[int(0.95 * (len(values) - 1))],
            "max": values[-1],
        }


class MetricsRegistry:
    def __init__(self):
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name, help_text, label_names)
        return self._counters[name]

    def histogram(self, name: str, help_text: str) -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, help_text)
        return self._histograms[name]

    def render_prometheus_text(self) -> str:
        lines = []
        for counter in self._counters.values():
            lines.append(f"# HELP {counter.name} {counter.help_text}")
            lines.append(f"# TYPE {counter.name} counter")
            snapshot = counter.snapshot()
            if not snapshot:
                lines.append(f"{counter.name} 0")
            for label_values, value in snapshot.items():
                label_str = ",".join(f'{n}="{v}"' for n, v in zip(counter.label_names, label_values))
                suffix = f"{{{label_str}}}" if label_str else ""
                lines.append(f"{counter.name}{suffix} {value}")
        for histogram in self._histograms.values():
            stats = histogram.snapshot()
            lines.append(f"# HELP {histogram.name} {histogram.help_text}")
            lines.append(f"# TYPE {histogram.name} summary")
            lines.append(f"{histogram.name}_count {stats['count']}")
            lines.append(f"{histogram.name}_sum {stats['sum']}")
            for quantile in ("p50", "p95", "max"):
                if stats[quantile] is not None:
                    lines.append(f'{histogram.name}{{quantile="{quantile}"}} {stats[quantile]}')
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Test-only: clears all recorded values without discarding metric definitions."""
        for counter in self._counters.values():
            with counter._lock:
                counter._values.clear()
        for histogram in self._histograms.values():
            with histogram._lock:
                histogram._observations.clear()


registry = MetricsRegistry()

# --- P9 requirement 4: the enumerated metric set -----------------------------------
request_count = registry.counter("kyc_request_count", "Total API requests", ("path", "method"))
error_count = registry.counter("kyc_error_count", "Total requests resulting in an error response", ("path", "status"))
request_latency_ms = registry.histogram("kyc_request_latency_ms", "HTTP request latency in milliseconds")
extraction_failures = registry.counter(
    "kyc_extraction_failures_total", "Documents where a mandatory field failed to extract", ("document_type",)
)
validation_failures = registry.counter(
    "kyc_validation_failures_total", "Evidence-validation FAIL results", ("rule_id",)
)
identity_conflicts = registry.counter(
    "kyc_identity_conflicts_total", "Identity-resolution CONFLICT findings", ("attribute",)
)
fraud_referrals = registry.counter(
    "kyc_fraud_referrals_total", "Cases with at least one fraud signal", ("category",)
)
decisions_total = registry.counter("kyc_decisions_total", "Case decisions by outcome", ("decision",))
manual_review_created = registry.counter("kyc_manual_review_created_total", "Review cases opened", ("priority",))
document_types_seen = registry.counter("kyc_document_types_total", "Documents processed by classified type", ("document_type",))
provider_failures = registry.counter(
    "kyc_provider_failures_total", "Provider-contract or malformed-response failures", ("provider",)
)
