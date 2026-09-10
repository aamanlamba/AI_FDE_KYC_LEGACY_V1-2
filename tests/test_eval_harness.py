"""Tests for the evaluation harness (eval/) itself -- its own correctness, not a
duplicate of the metrics it computes about the KYC system. This is part of the
ordinary pytest regression suite (P7 requirement 1: preserve existing regression
tests -- this file adds to that suite rather than replacing anything in it)."""

import json


from eval.cases import build_eval_cases
from eval.gates import evaluate_gates
from eval.metamorphic import run_metamorphic_suite
from eval.metrics import _rate, document_intelligence_metrics, FAR_FRR_SEMANTICS
from eval.report import build_report, write_report
from eval.runner import run_eval_case


REQUIRED_CATEGORIES = {
    "golden", "noisy", "rotated", "ocr_corrupted", "expired", "identity_variation",
    "fraud_tampering", "missing_evidence", "contradictory_evidence", "adversarial_malformed",
}


# --- case catalogue completeness (P7 requirement 3) --------------------------------

def test_every_required_category_is_represented():
    cases = build_eval_cases()
    present = {c.category for c in cases}
    missing = REQUIRED_CATEGORIES - present
    assert not missing, f"eval categories missing: {missing}"


def test_synthetic_categories_never_touch_the_data_directory():
    # missing_evidence / contradictory_evidence / adversarial_malformed must not
    # reference any repository case_id or fixture file.
    for case in build_eval_cases():
        if case.category in ("missing_evidence", "contradictory_evidence", "adversarial_malformed"):
            assert case.source == "synthetic"
            assert case.repo_case_id is None


# --- runner: exceptions are captured, not propagated -------------------------------

def test_runner_captures_expected_exception_without_crashing_the_harness():
    from eval.cases import EvalCase

    bad_case = EvalCase(
        case_id="TEST-UNKNOWN-CASE", category="adversarial_malformed",
        description="deliberately unknown case_id", source="repository",
        repo_case_id="CASE-DOES-NOT-EXIST", expect_exception=FileNotFoundError,
    )
    record = run_eval_case(bad_case)
    assert record.raised
    assert isinstance(record.exception, FileNotFoundError)
    assert record.exception_was_expected


def test_runner_flags_an_unexpected_exception():
    from eval.cases import EvalCase

    bad_case = EvalCase(
        case_id="TEST-UNKNOWN-CASE-2", category="adversarial_malformed",
        description="unknown case_id with no exception expectation declared",
        source="repository", repo_case_id="CASE-DOES-NOT-EXIST",
    )
    record = run_eval_case(bad_case)
    assert record.raised
    assert not record.exception_was_expected


# --- metrics helpers -----------------------------------------------------------------

def test_rate_helper_reports_sample_size_and_warns_on_small_n():
    small = _rate(5, 6)
    assert small["numerator"] == 5 and small["denominator"] == 6
    assert small["rate"] == round(5 / 6, 4)
    assert small["sample_size_warning"] is True  # n=6 < 30

    large = _rate(500, 1000)
    assert large["sample_size_warning"] is False


def test_rate_helper_handles_zero_denominator_without_crashing():
    result = _rate(0, 0)
    assert result["rate"] is None


def test_far_frr_semantics_are_stated_explicitly():
    assert "not" in FAR_FRR_SEMANTICS.lower()
    assert "population" in FAR_FRR_SEMANTICS.lower()


def test_document_intelligence_metrics_flag_the_known_ocr_corruption():
    from eval.runner import run_all
    from eval.cases import build_eval_cases as _build

    records = run_all([c for c in _build() if c.category in ("golden", "ocr_corrupted")])
    di = document_intelligence_metrics(records)
    # 6 comparable fields on the golden passport all match; the OCR-corrupted case's
    # full_name is a known, deliberate mismatch.
    assert di["exact_match"]["numerator"] < di["exact_match"]["denominator"]
    assert di["per_field"]["full_name"]["exact"] < di["per_field"]["full_name"]["total"]


# --- metamorphic suite: invariance and sensitivity are both exercised ---------------

def test_metamorphic_suite_covers_both_kinds():
    results = run_metamorphic_suite()
    kinds = {r.kind for r in results}
    assert kinds == {"invariance", "adversarial_sensitivity"}
    assert len(results) >= 6  # at least 4 invariance + 3 sensitivity is the design intent, minus overlap tolerance


def test_metamorphic_suite_currently_passes_end_to_end():
    results = run_metamorphic_suite()
    failures = [r.name for r in results if not r.passed]
    assert not failures, f"metamorphic checks failed: {failures}"


# --- release gates: the mechanism itself is sound, not vacuous ---------------------

def test_gates_fail_when_given_a_deliberately_bad_report():
    broken_report = {
        "eval_case_count": 5,
        "operations": {"unexpected_exception_count": 2},
        "metamorphic": {
            "invariance_pass_rate": {"numerator": 3, "denominator": 4, "rate": 0.75},
            "adversarial_sensitivity_pass_rate": {"numerator": 3, "denominator": 3, "rate": 1.0},
        },
        "decisioning": {
            "false_acceptance": {"numerator": 1, "denominator": 3},
            "decision_accuracy": {"numerator": 8, "denominator": 10, "rate": 0.8},
        },
        "document_intelligence": {"exact_match": {"numerator": 80, "denominator": 84, "rate": 0.952}},
    }
    gates = evaluate_gates(broken_report)
    failed_names = {g["name"] for g in gates if not g["passed"]}
    assert "no_unexpected_exceptions" in failed_names
    assert "metamorphic_invariance_holds" in failed_names
    assert "zero_false_acceptance_on_labeled_problem_cases" in failed_names
    assert "decision_accuracy_at_least_90_percent" in failed_names
    assert "adversarial_sensitivity_holds" not in failed_names  # this one was clean in the broken report


def test_gates_pass_on_a_clean_report():
    clean_report = {
        "eval_case_count": 11,
        "operations": {"unexpected_exception_count": 0},
        "metamorphic": {
            "invariance_pass_rate": {"numerator": 4, "denominator": 4, "rate": 1.0},
            "adversarial_sensitivity_pass_rate": {"numerator": 3, "denominator": 3, "rate": 1.0},
        },
        "decisioning": {
            "false_acceptance": {"numerator": 0, "denominator": 3},
            "decision_accuracy": {"numerator": 10, "denominator": 10, "rate": 1.0},
        },
        "document_intelligence": {"exact_match": {"numerator": 82, "denominator": 84, "rate": 0.976}},
    }
    gates = evaluate_gates(clean_report)
    assert all(g["passed"] for g in gates)


# --- full report: JSON round-trip and current release-gate status ------------------

def test_full_report_round_trips_through_json_and_contains_required_sections(tmp_path):
    report = build_report(latency_samples=3)
    path = write_report(report, tmp_path / "report.json")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "document_intelligence", "identity_resolution", "decisioning", "operations",
        "metamorphic", "gates", "release_gate_status", "sample_size_disclaimer",
    ):
        assert key in reloaded


def test_current_system_passes_its_own_release_gates():
    report = build_report(latency_samples=3)
    failed = [g["name"] for g in report["gates"] if not g["passed"]]
    assert not failed, f"release gates failed against the current system: {failed}"
    assert report["release_gate_status"] == "PASS"
