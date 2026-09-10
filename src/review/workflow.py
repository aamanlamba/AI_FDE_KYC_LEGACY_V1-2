from datetime import datetime, timezone
from uuid import uuid4

from ..evidence_validation.models import Severity, ValidationStatus
from ..identity_resolution import MatchStatus
from ..models import CaseResult
from .errors import ReviewNotEligibleError
from .models import EvidenceSummary, ReviewCase, ReviewPriority, ReviewStatus
from .store import ReviewStore
from .summary import DeterministicReviewSummaryProvider, ReviewSummaryProvider

_SEVERITY_RANK = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}
_KEY_FIELDS = ("full_name", "date_of_birth")


def _derive_trigger_and_priority(risk_factors) -> tuple[str, ReviewPriority]:
    if not risk_factors:
        return "NONE", ReviewPriority.LOW
    top = max(risk_factors, key=lambda f: _SEVERITY_RANK[f.severity])
    rank = _SEVERITY_RANK[top.severity]
    if rank >= _SEVERITY_RANK[Severity.HIGH]:
        priority = ReviewPriority.HIGH
    elif rank >= _SEVERITY_RANK[Severity.MEDIUM]:
        priority = ReviewPriority.MEDIUM
    else:
        priority = ReviewPriority.LOW
    return top.category.value, priority


def _build_evidence_summary(case_result: CaseResult) -> EvidenceSummary:
    key_fields: dict[str, dict[str, str | None]] = {}
    for doc in case_result.documents:
        key_fields[doc.document_id] = {
            name: (doc.evidence.fields[name].value if name in doc.evidence.fields else None)
            for name in _KEY_FIELDS
        }
    return EvidenceSummary(
        document_count=len(case_result.documents),
        document_types=sorted({d.evidence.document_type.value for d in case_result.documents}),
        key_fields=key_fields,
    )


def _discrepancies(case_result: CaseResult) -> list[str]:
    discrepancies = list(case_result.identity_resolution.conflicts)
    for attribute_comparison in case_result.identity_resolution.attribute_comparisons:
        if attribute_comparison.status == MatchStatus.FUZZY_MATCH:
            sources = ", ".join(s.source_id for s in attribute_comparison.sources if s.raw_value is not None)
            discrepancies.append(f"{attribute_comparison.attribute}: fuzzy match only across {sources}")
    return discrepancies


def _failed_validations(case_result: CaseResult) -> list[str]:
    failures = []
    for doc in case_result.documents:
        failures += [
            f"{doc.document_id}: {result.explanation}"
            for result in doc.validation.results
            if result.status == ValidationStatus.FAIL
        ]
    failures += [
        f"{case_result.case_id}: {result.explanation}"
        for result in case_result.validation.case_level_results
        if result.status == ValidationStatus.FAIL
    ]
    return failures


def _fraud_signal_descriptions(case_result: CaseResult) -> list[str]:
    all_signals = [s for ds in case_result.fraud_assessment.document_signals for s in ds.signals]
    all_signals += case_result.fraud_assessment.case_level_signals
    return [f"{s.category.value} ({s.severity.value}): {s.explanation}" for s in all_signals]


def open_review_case(
    case_result: CaseResult,
    store: ReviewStore,
    summary_provider: ReviewSummaryProvider | None = None,
) -> ReviewCase:
    """Open (or return the existing open) review case for a CaseResult.

    Only a REVIEW decision may enter this ordinary review workflow -- no alternate
    policy route into it is defined anywhere in this repository today, so any other
    decision is rejected rather than silently accepted.
    """
    if case_result.decision != "REVIEW":
        raise ReviewNotEligibleError(
            f"case {case_result.case_id} has decision {case_result.decision!r}; only REVIEW "
            f"decisions may open an ordinary review case (no alternate route is defined)."
        )

    existing = store.find_open_review_for_case(case_result.case_id)
    if existing is not None:
        return existing

    provider = summary_provider or DeterministicReviewSummaryProvider()
    trigger, priority = _derive_trigger_and_priority(case_result.risk_assessment.risk_factors)

    review = ReviewCase(
        review_id=f"RVW-{case_result.case_id}-{uuid4().hex[:8]}",
        case_id=case_result.case_id,
        trigger=trigger,
        priority=priority,
        evidence_summary=_build_evidence_summary(case_result),
        discrepancies=_discrepancies(case_result),
        failed_validations=_failed_validations(case_result),
        fraud_signals=_fraud_signal_descriptions(case_result),
        reason_codes=case_result.reason_codes,
        status=ReviewStatus.OPEN,
        created_at=datetime.now(timezone.utc).isoformat(),
        policy_version=case_result.risk_assessment.policy_version,
        reviewer_summary=provider.summarize(case_result, case_result.risk_assessment),
    )
    store.create_review(review)
    return review
