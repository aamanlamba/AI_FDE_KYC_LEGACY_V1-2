"""Metric computation. Every function returns a plain dict (JSON-serializable) and
every rate is accompanied by the raw (numerator, denominator) counts it was computed
from -- P7 requirement 6: never report a percentage without its sample size.
"""

import statistics

from src.repository import load_ground_truth

from .cases import GROUND_TRUTH_FIELDS, EvalCase
from .runner import CaseRunRecord

FAR_FRR_SEMANTICS = (
    "FAR/FRR here are NOT a calibrated error rate against any real population. This "
    "repository's decision policy (src/decision_policy/) is a deterministic rule "
    "engine, not a statistical or biometric classifier, and the 'ground truth' used "
    "below is the scenario-design label of each hand-curated evaluation case (what the "
    "case was built to represent), not an independently-verified population base rate. "
    "False Acceptance (FA): an eval case whose scenario design represents a genuine "
    "problem (fraud/tamper marker, contradictory evidence) that the system's decision "
    "nonetheless APPROVEs. False Rejection (FR): an eval case whose scenario design "
    "represents genuinely clean evidence (no fraud/tamper/contradiction) that the "
    "system's decision nonetheless REJECTs. Both are measured only over the small, "
    "adversarial-weighted case set in eval/cases.py -- they estimate regression risk on "
    "known scenarios, not real-world error rates."
)


def _rate(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
        "sample_size_warning": denominator < 30,
    }


def _normalize_for_comparison(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split())


def document_intelligence_metrics(records: list[CaseRunRecord]) -> dict:
    exact_matches = 0
    normalized_matches = 0
    total_comparable = 0
    missing_count = 0
    true_positive = 0  # expected present, extracted present
    false_negative = 0  # expected present, extracted missing
    false_positive = 0  # extracted present, not expected (i.e. ground truth null)

    per_field: dict[str, dict[str, int]] = {}

    for record in records:
        if not record.case.ground_truth_document_ids or record.raised:
            continue
        evidence_by_doc = {e.document_id: e for e in record.documents_evidence}
        for doc_id in record.case.ground_truth_document_ids:
            evidence = evidence_by_doc.get(doc_id)
            if evidence is None:
                continue
            gt = load_ground_truth(doc_id)
            for field_name in GROUND_TRUTH_FIELDS:
                gt_value = gt.get(field_name)
                extracted_field = evidence.fields.get(field_name)
                extracted_value = extracted_field.value if extracted_field else None

                bucket = per_field.setdefault(field_name, {"exact": 0, "normalized": 0, "total": 0, "missing": 0})

                if gt_value is None:
                    if extracted_value is not None:
                        false_positive += 1
                    continue  # not a comparable field for this document type

                total_comparable += 1
                bucket["total"] += 1
                if extracted_value is None:
                    missing_count += 1
                    false_negative += 1
                    bucket["missing"] += 1
                    continue
                true_positive += 1
                if extracted_value == gt_value:
                    exact_matches += 1
                    bucket["exact"] += 1
                if _normalize_for_comparison(extracted_value) == _normalize_for_comparison(gt_value):
                    normalized_matches += 1
                    bucket["normalized"] += 1

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = round(true_positive / precision_denominator, 4) if precision_denominator else None
    recall = round(true_positive / recall_denominator, 4) if recall_denominator else None
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall and (precision + recall) else None

    return {
        "exact_match": _rate(exact_matches, total_comparable),
        "normalized_match": _rate(normalized_matches, total_comparable),
        "missing_field_rate": _rate(missing_count, total_comparable),
        "field_presence_precision": {"value": precision, "tp": true_positive, "fp": false_positive},
        "field_presence_recall": {"value": recall, "tp": true_positive, "fn": false_negative},
        "field_presence_f1": f1,
        "per_field": per_field,
        "note": "Computed over repository-sourced eval cases with ground_truth_document_ids only "
                "(synthetic missing-evidence cases are reported separately below, not blended in).",
    }


def missing_evidence_category_metrics(records: list[CaseRunRecord]) -> dict:
    """The synthetic 'missing_evidence' category reported on its own -- deliberately
    separate from document_intelligence_metrics' real-dataset numbers, so a 0%
    missing-field rate on the golden dataset is never misread as 'the system never
    has missing fields' (P7 requirement 6: state sample size, don't blend populations)."""
    relevant = [r for r in records if r.case.category == "missing_evidence" and not r.raised]
    missing = 0
    total = 0
    for record in relevant:
        for evidence in record.documents_evidence:
            for field in evidence.fields.values():
                total += 1
                if field.value is None:
                    missing += 1
    return {"cases_evaluated": len(relevant), "missing_field_rate": _rate(missing, total)}


def identity_resolution_metrics(records: list[CaseRunRecord]) -> dict:
    status_labeled = [r for r in records if r.case.expected_identity_status is not None and not r.raised]
    status_correct = sum(1 for r in status_labeled if r.identity_overall_status == r.case.expected_identity_status)

    conflict_labeled = [r for r in records if r.case.should_have_identity_conflict is not None and not r.raised]
    conflict_correct = sum(
        1 for r in conflict_labeled if r.has_identity_conflict == r.case.should_have_identity_conflict
    )

    return {
        "match_status_accuracy": _rate(status_correct, len(status_labeled)),
        "conflict_detection_accuracy": _rate(conflict_correct, len(conflict_labeled)),
    }


def decisioning_metrics(records: list[CaseRunRecord]) -> dict:
    labeled = [r for r in records if r.case.expected_decision is not None and not r.raised]
    correct = sum(1 for r in labeled if r.decision == r.case.expected_decision)

    # A "problem" case is one whose scenario design represents genuine fraud/tamper/
    # contradiction (categories fraud_tampering, contradictory_evidence) or an
    # explicit should_have_identity_conflict=True label.
    problem_cases = [
        r for r in records
        if not r.raised and (r.case.category in ("fraud_tampering", "contradictory_evidence") or r.case.should_have_identity_conflict is True)
    ]
    false_acceptances = [r for r in problem_cases if r.decision == "APPROVE"]

    # A "clean" case is one whose scenario design represents no fraud/tamper/
    # contradiction/identity conflict at all.
    clean_cases = [
        r for r in records
        if not r.raised and r.case.category in ("golden", "noisy", "rotated") and r.case.should_have_identity_conflict is not True
    ]
    false_rejections = [r for r in clean_cases if r.decision == "REJECT"]

    reviewed = sum(1 for r in records if not r.raised and r.decision == "REVIEW")
    decided = sum(1 for r in records if not r.raised and r.decision is not None)

    return {
        "far_frr_semantics": FAR_FRR_SEMANTICS,
        "decision_accuracy": _rate(correct, len(labeled)),
        "false_acceptance": {
            **_rate(len(false_acceptances), len(problem_cases)),
            "false_acceptance_case_ids": [r.case.case_id for r in false_acceptances],
        },
        "false_rejection": {
            **_rate(len(false_rejections), len(clean_cases)),
            "false_rejection_case_ids": [r.case.case_id for r in false_rejections],
        },
        "review_referral_rate": _rate(reviewed, decided),
    }


def operations_metrics(records: list[CaseRunRecord], repeated_latencies_ms: list[float]) -> dict:
    unexpected_exceptions = [r for r in records if r.raised and not r.exception_was_expected]
    expected_exceptions_missed = [r for r in records if not r.raised and r.case.expect_exception is not None]

    real_dataset = [r for r in records if r.case.source == "repository" and r.case.category != "ocr_corrupted" and not r.raised]
    # ocr_corrupted intentionally reuses CASE-005's case_id for a document-level check;
    # exclude it here to avoid double-counting CASE-005 in the case-level STP rate.
    stp = sum(1 for r in real_dataset if r.decision in ("APPROVE", "REJECT"))

    latency_stats = None
    if repeated_latencies_ms:
        sorted_latencies = sorted(repeated_latencies_ms)
        latency_stats = {
            "n": len(sorted_latencies),
            "mean_ms": round(statistics.mean(sorted_latencies), 3),
            "median_ms": round(statistics.median(sorted_latencies), 3),
            "p95_ms": round(sorted_latencies[int(0.95 * (len(sorted_latencies) - 1))], 3),
            "max_ms": round(max(sorted_latencies), 3),
            "caveat": "In-process verify_case() calls, no HTTP/ASGI overhead, single-threaded, "
                      "warm OS page cache. Not a substitute for a real load/latency test.",
        }

    return {
        "straight_through_processing_rate": _rate(stp, len(real_dataset)),
        "unexpected_exception_count": len(unexpected_exceptions),
        "unexpected_exception_case_ids": [r.case.case_id for r in unexpected_exceptions],
        "expected_exception_not_raised_case_ids": [r.case.case_id for r in expected_exceptions_missed],
        "error_rate": _rate(len(unexpected_exceptions), len(records)),
        "latency": latency_stats,
    }
