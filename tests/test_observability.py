"""Tests for telemetry emission and sensitive-data suppression (P9 requirement 13)."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

import src.app as appmod
from src.observability import (
    InMemorySpanExporter,
    JsonFormatter,
    bind_trace_context,
    build_decision_lineage,
    component_versions,
    get_current_trace_context,
    set_default_exporter,
    start_span,
)
from src.observability.metrics import MetricsRegistry
from src.observability.tracing import ALLOWED_SPAN_ATTRIBUTE_KEYS
from src.service import verify_case


@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    previous = set_default_exporter(exporter)
    try:
        yield exporter
    finally:
        set_default_exporter(previous)


# --- one trace context across every component (requirement 1) ----------------------

def test_verify_case_produces_a_fully_nested_span_tree(span_exporter):
    with bind_trace_context(trace_id="trace-nesting-test"):
        verify_case("CASE-005")

    names = {s.name for s in span_exporter.spans}
    for expected in (
        "service.verify_case", "service.verify_document", "document_intelligence.extract",
        "evidence_validation.validate_document", "fraud_signals.assess_document",
        "identity_resolution.resolve", "evidence_validation.validate_case",
        "fraud_signals.assess_case", "decision_policy.assess",
    ):
        assert expected in names, f"missing span: {expected}"

    assert all(s.trace_id == "trace-nesting-test" for s in span_exporter.spans)
    root = next(s for s in span_exporter.spans if s.name == "service.verify_case")
    assert root.parent_span_id is None
    children = [s for s in span_exporter.spans if s.parent_span_id == root.span_id]
    assert {"service.verify_document", "identity_resolution.resolve", "evidence_validation.validate_case",
            "fraud_signals.assess_case", "decision_policy.assess"} <= {c.name for c in children}


def test_review_creation_is_traced_under_the_same_context(span_exporter):
    from src.review import ReviewStore, open_review_case

    store = ReviewStore(":memory:")
    with bind_trace_context(trace_id="trace-review-test"):
        case_result = verify_case("CASE-005")
        open_review_case(case_result, store)

    review_spans = [s for s in span_exporter.spans if s.name == "review.open"]
    assert len(review_spans) == 1
    assert review_spans[0].trace_id == "trace-review-test"


def test_every_span_completes_with_a_duration():
    exporter = InMemorySpanExporter()
    previous = set_default_exporter(exporter)
    try:
        with bind_trace_context():
            with start_span("test.span", case_id="CASE-001"):
                pass
    finally:
        set_default_exporter(previous)
    assert exporter.spans[0].duration_ms is not None and exporter.spans[0].duration_ms >= 0


def test_span_marks_error_status_when_the_block_raises():
    exporter = InMemorySpanExporter()
    previous = set_default_exporter(exporter)
    try:
        with bind_trace_context():
            with pytest.raises(ValueError):
                with start_span("test.failing_span", case_id="CASE-001"):
                    raise ValueError("boom")
    finally:
        set_default_exporter(previous)
    assert exporter.spans[0].status == "ERROR"


# --- span attributes never carry sensitive content (requirement 3) -----------------

def test_span_attribute_allowlist_rejects_identity_fields():
    with bind_trace_context():
        with pytest.raises(ValueError):
            with start_span("test.span", full_name="Aarav Mehta"):
                pass


def test_no_real_span_in_the_pipeline_ever_uses_a_disallowed_attribute_key(span_exporter):
    with bind_trace_context():
        verify_case("CASE-005")
    for span in span_exporter.spans:
        assert set(span.attributes) <= ALLOWED_SPAN_ATTRIBUTE_KEYS


# --- structured logging (requirement 2) ---------------------------------------------

def test_json_formatter_produces_valid_parseable_json():
    record = logging.LogRecord("kyc-v1", logging.INFO, __file__, 1, "hello", None, None)
    record.trace_id = "t1"
    record.correlation_id = "c1"
    rendered = JsonFormatter().format(record)
    parsed = json.loads(rendered)
    assert parsed["message"] == "hello"
    assert parsed["trace_id"] == "t1"
    assert parsed["level"] == "INFO"


def test_json_formatter_includes_extra_fields_as_structured_data():
    record = logging.LogRecord("kyc-v1", logging.INFO, __file__, 1, "event happened", None, None)
    record.trace_id = "t1"
    record.correlation_id = "c1"
    record.case_id = "CASE-001"
    record.decision = "APPROVE"
    parsed = json.loads(JsonFormatter().format(record))
    assert parsed["case_id"] == "CASE-001"
    assert parsed["decision"] == "APPROVE"


# --- sensitive-data suppression in real HTTP logs (requirement 3, 10) --------------

def test_no_identity_attribute_appears_in_captured_structured_logs(caplog):
    client = TestClient(appmod.app)
    with caplog.at_level(logging.INFO):
        client.post("/v1/cases/CASE-005/verify")
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for pii_value in ("Mohammed Rahman", "Moharnmad Rehrnan", "PXT500578", "1992-12-08"):
        assert pii_value not in log_text


# --- metrics (requirement 4) ---------------------------------------------------------

def test_counter_and_histogram_render_prometheus_compatible_text():
    registry = MetricsRegistry()
    counter = registry.counter("test_counter", "a test counter", ("label",))
    counter.inc(label="x")
    histogram = registry.histogram("test_histogram", "a test histogram")
    histogram.observe(1.5)
    histogram.observe(2.5)
    text = registry.render_prometheus_text()
    assert "# HELP test_counter a test counter" in text
    assert "# TYPE test_counter counter" in text
    assert 'test_counter{label="x"} 1.0' in text
    assert "test_histogram_count 2" in text


def test_metrics_endpoint_reflects_real_pipeline_activity():
    from src.observability import metrics as obs_metrics

    obs_metrics.registry.reset()
    client = TestClient(appmod.app)
    client.post("/v1/cases/CASE-005/verify")
    client.post("/v1/documents/verify", json={"document_id": "CASE-001-PASSPORT"})
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "kyc_identity_conflicts_total" in body
    assert 'attribute="full_name"' in body
    assert "kyc_decisions_total" in body
    assert 'decision="REVIEW"' in body
    assert "kyc_document_types_total" in body
    obs_metrics.registry.reset()


def test_error_count_increments_on_a_4xx_response():
    from src.observability import metrics as obs_metrics

    obs_metrics.registry.reset()
    client = TestClient(appmod.app)
    client.post("/v1/cases/CASE-999/verify")  # unknown case -> 404
    snapshot = obs_metrics.error_count.snapshot()
    assert any(v >= 1 for v in snapshot.values())
    obs_metrics.registry.reset()


def test_manual_review_created_metric_increments():
    from src.observability import metrics as obs_metrics
    from src.review import ReviewStore, open_review_case

    obs_metrics.registry.reset()
    store = ReviewStore(":memory:")
    open_review_case(verify_case("CASE-005"), store)
    snapshot = obs_metrics.manual_review_created.snapshot()
    assert sum(snapshot.values()) == 1
    obs_metrics.registry.reset()


# --- health/ready verifies meaningful dependencies (requirement 5) -----------------

def test_health_ready_reports_per_dependency_checks():
    client = TestClient(appmod.app)
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["dataset"] == "ok"
    assert body["checks"]["review_store"] == "ok"
    assert body["checks"]["auth_config"] == "ok"


# --- decision lineage (requirement 8, 9) --------------------------------------------

def test_decision_lineage_captures_trace_policy_and_component_versions():
    with bind_trace_context(trace_id="lineage-test-trace"):
        result = verify_case("CASE-005")
    lineage = result.decision_lineage
    assert lineage.trace_id == "lineage-test-trace"
    assert lineage.case_id == "CASE-005"
    assert lineage.decision == result.decision
    assert lineage.policy_version == result.risk_assessment.policy_version
    assert lineage.component_versions == component_versions()
    assert lineage.evidence_reference_count > 0
    assert any("identity_conflict" in item for item in lineage.risk_factor_summary)


def test_decision_lineage_is_reconstructable_from_the_case_result_alone():
    # Success criterion: an auditor with only the CaseResult JSON (no source access)
    # can see exactly which policy/component versions and which risk factors produced
    # the decision.
    result = verify_case("CASE-004")
    dumped = result.model_dump(mode="json")
    lineage = dumped["decision_lineage"]
    assert lineage["decision"] == dumped["decision"]
    assert lineage["policy_version"]
    assert set(lineage["component_versions"]) == {
        "decision_policy", "evidence_validation", "identity_resolution",
        "document_intelligence_provider", "fraud_forensics_provider",
    }


def test_build_decision_lineage_is_a_pure_function_of_its_inputs():
    result = verify_case("CASE-001")
    ctx = get_current_trace_context()
    lineage_a = build_decision_lineage("CASE-001", result.decision, result.risk_assessment, ctx)
    lineage_b = build_decision_lineage("CASE-001", result.decision, result.risk_assessment, ctx)
    assert lineage_a == lineage_b


# --- context propagation without an active HTTP request ---------------------------

def test_trace_context_is_available_outside_of_an_http_request():
    # scripts/eval harness/tests all call verify_case directly, with no HTTP request
    # in play -- get_current_trace_context must still return something usable.
    ctx = get_current_trace_context()
    assert ctx.trace_id and ctx.correlation_id


def test_bind_trace_context_is_isolated_between_calls():
    with bind_trace_context(trace_id="isolated-a"):
        ctx_a = get_current_trace_context()
    with bind_trace_context(trace_id="isolated-b"):
        ctx_b = get_current_trace_context()
    assert ctx_a.trace_id == "isolated-a"
    assert ctx_b.trace_id == "isolated-b"
