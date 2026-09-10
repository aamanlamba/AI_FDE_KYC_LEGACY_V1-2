import json
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import metrics as metrics_mod
from .cases import build_eval_cases
from .metamorphic import run_metamorphic_suite
from .runner import run_all
from .gates import evaluate_gates

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "var" / "eval" / "report.json"


def _repeated_latency_sample_ms(n: int = 30) -> list[float]:
    """A small, explicit-n repeated-call latency sample over the real dataset's
    6 cases. See metrics.operations_metrics for the caveats attached to this number."""
    import time

    from src.repository import list_cases
    from src.service import verify_case

    case_ids = [c["case_id"] for c in list_cases()]
    if not case_ids:
        return []
    samples = []
    for i in range(n):
        start = time.perf_counter()
        verify_case(case_ids[i % len(case_ids)])
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def build_report(latency_samples: int = 30) -> dict:
    eval_cases = build_eval_cases()
    records = run_all(eval_cases)
    metamorphic_results = run_metamorphic_suite()
    latencies_ms = _repeated_latency_sample_ms(latency_samples)

    category_counts: dict[str, int] = {}
    for c in eval_cases:
        category_counts[c.category] = category_counts.get(c.category, 0) + 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "eval_case_count": len(eval_cases),
        "eval_categories": category_counts,
        "sample_size_disclaimer": (
            "This evaluation runs against a small, hand-curated, deliberately "
            f"adversarial-weighted case set ({len(eval_cases)} eval cases, drawn from a "
            "6-case/13-document synthetic dataset plus a handful of synthetic edge "
            "cases). No percentage in this report should be read as a statistically "
            "significant estimate over any real population. Every rate below is "
            "reported alongside its raw numerator/denominator for exactly this reason."
        ),
        "document_intelligence": metrics_mod.document_intelligence_metrics(records),
        "missing_evidence_category": metrics_mod.missing_evidence_category_metrics(records),
        "identity_resolution": metrics_mod.identity_resolution_metrics(records),
        "decisioning": metrics_mod.decisioning_metrics(records),
        "operations": metrics_mod.operations_metrics(records, latencies_ms),
        "metamorphic": {
            "results": [asdict(r) for r in metamorphic_results],
            "invariance_pass_rate": _pass_rate(metamorphic_results, "invariance"),
            "adversarial_sensitivity_pass_rate": _pass_rate(metamorphic_results, "adversarial_sensitivity"),
        },
        "cases": [
            {
                "case_id": r.case.case_id,
                "category": r.case.category,
                "source": r.case.source,
                "decision": r.decision,
                "expected_decision": r.case.expected_decision,
                "identity_overall_status": r.identity_overall_status,
                "raised_exception": r.raised,
                "exception_type": type(r.exception).__name__ if r.exception else None,
                "exception_expected": r.case.expect_exception.__name__ if r.case.expect_exception else None,
                "latency_ms": round(r.latency_seconds * 1000, 3),
            }
            for r in records
        ],
    }

    report["gates"] = evaluate_gates(report)
    report["release_gate_status"] = "PASS" if all(g["passed"] for g in report["gates"]) else "FAIL"
    return report


def _pass_rate(results, kind: str) -> dict:
    relevant = [r for r in results if r.kind == kind]
    passed = sum(1 for r in relevant if r.passed)
    return {
        "numerator": passed, "denominator": len(relevant),
        "rate": round(passed / len(relevant), 4) if relevant else None,
    }


def write_report(report: dict, path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def print_summary(report: dict) -> None:
    print(f"Evaluation run: {report['generated_at']}")
    print(f"Eval cases: {report['eval_case_count']} across categories {report['eval_categories']}")
    print()
    di = report["document_intelligence"]
    print(f"Document Intelligence: exact_match={di['exact_match']['rate']} "
          f"({di['exact_match']['numerator']}/{di['exact_match']['denominator']}), "
          f"normalized_match={di['normalized_match']['rate']}, "
          f"missing_field_rate={di['missing_field_rate']['rate']}, "
          f"F1={di['field_presence_f1']}")
    ir = report["identity_resolution"]
    print(f"Identity Resolution: match_status_accuracy={ir['match_status_accuracy']['rate']} "
          f"({ir['match_status_accuracy']['numerator']}/{ir['match_status_accuracy']['denominator']}), "
          f"conflict_detection_accuracy={ir['conflict_detection_accuracy']['rate']} "
          f"({ir['conflict_detection_accuracy']['numerator']}/{ir['conflict_detection_accuracy']['denominator']})")
    dec = report["decisioning"]
    print(f"Decisioning: decision_accuracy={dec['decision_accuracy']['rate']} "
          f"({dec['decision_accuracy']['numerator']}/{dec['decision_accuracy']['denominator']}), "
          f"FA={dec['false_acceptance']['numerator']}/{dec['false_acceptance']['denominator']}, "
          f"FR={dec['false_rejection']['numerator']}/{dec['false_rejection']['denominator']}, "
          f"review_rate={dec['review_referral_rate']['rate']}")
    ops = report["operations"]
    print(f"Operations: STP_rate={ops['straight_through_processing_rate']['rate']} "
          f"({ops['straight_through_processing_rate']['numerator']}/{ops['straight_through_processing_rate']['denominator']}), "
          f"error_rate={ops['error_rate']['rate']} ({ops['unexpected_exception_count']} unexpected exceptions), "
          f"latency_median_ms={ops['latency']['median_ms'] if ops['latency'] else 'n/a'}")
    mm = report["metamorphic"]
    print(f"Metamorphic: invariance={mm['invariance_pass_rate']['numerator']}/{mm['invariance_pass_rate']['denominator']}, "
          f"adversarial_sensitivity={mm['adversarial_sensitivity_pass_rate']['numerator']}/{mm['adversarial_sensitivity_pass_rate']['denominator']}")
    print()
    print("Release gates:")
    for gate in report["gates"]:
        status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{status}] {gate['name']}: {gate['detail']}")
    print()
    print(f"RELEASE GATE STATUS: {report['release_gate_status']}")
