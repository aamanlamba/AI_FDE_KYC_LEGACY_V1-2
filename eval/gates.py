"""Release gates: pass/fail thresholds a CI pipeline can check before shipping a
change. Deliberately few and each individually justified -- a gate that can never fail
given a correct system is worse than no gate (false confidence), so every threshold
here is set at what a genuinely correct system is expected to satisfy today, verified
by actually running the suite.
"""

from typing import Callable


def _gate(name: str, detail: str, passed: bool) -> dict:
    return {"name": name, "passed": passed, "detail": detail}


def _no_unexpected_exceptions(r: dict) -> dict:
    return _gate(
        "no_unexpected_exceptions",
        f"{r['operations']['unexpected_exception_count']} unexpected exception(s) across "
        f"{r['eval_case_count']} eval cases",
        r["operations"]["unexpected_exception_count"] == 0,
    )


def _metamorphic_invariance_holds(r: dict) -> dict:
    p = r["metamorphic"]["invariance_pass_rate"]
    return _gate(
        "metamorphic_invariance_holds",
        f"{p['numerator']}/{p['denominator']} harmless-change invariance checks passed",
        p["rate"] == 1.0,
    )


def _adversarial_sensitivity_holds(r: dict) -> dict:
    p = r["metamorphic"]["adversarial_sensitivity_pass_rate"]
    return _gate(
        "adversarial_sensitivity_holds",
        f"{p['numerator']}/{p['denominator']} adversarial-sensitivity checks passed",
        p["rate"] == 1.0,
    )


def _zero_false_acceptance(r: dict) -> dict:
    fa = r["decisioning"]["false_acceptance"]
    return _gate(
        "zero_false_acceptance_on_labeled_problem_cases",
        f"{fa['numerator']}/{fa['denominator']} labeled fraud/tamper/contradiction cases "
        f"were APPROVEd (must be 0)",
        fa["numerator"] == 0,
    )


def _decision_accuracy_floor(r: dict) -> dict:
    acc = r["decisioning"]["decision_accuracy"]
    return _gate(
        "decision_accuracy_at_least_90_percent",
        f"decision_accuracy={acc['rate']} ({acc['numerator']}/{acc['denominator']}) on the small "
        f"labeled eval set (see sample_size_disclaimer)",
        (acc["rate"] or 0) >= 0.9,
    )


def _document_field_exact_match_floor(r: dict) -> dict:
    em = r["document_intelligence"]["exact_match"]
    return _gate(
        "document_field_exact_match_at_least_95_percent",
        f"exact_match={em['rate']} ({em['numerator']}/{em['denominator']}) on the real synthetic "
        f"dataset (includes the one deliberately-OCR-corrupted field; see per_field breakdown)",
        (em["rate"] or 0) >= 0.95,
    )


_GATE_DEFINITIONS: list[Callable[[dict], dict]] = [
    _no_unexpected_exceptions,
    _metamorphic_invariance_holds,
    _adversarial_sensitivity_holds,
    _zero_false_acceptance,
    _decision_accuracy_floor,
    _document_field_exact_match_floor,
]


def evaluate_gates(report: dict) -> list[dict]:
    return [gate_fn(report) for gate_fn in _GATE_DEFINITIONS]
