from abc import ABC, abstractmethod

from ..decision_policy import RiskAssessment
from ..models import CaseResult


class ReviewSummaryProvider(ABC):
    """Interface for generating a reviewer-facing summary of a case under review.

    No LLM is called anywhere in this repository today. If an LLM-generated summary
    capability were ever introduced, any such implementation of this interface would
    still be required to:
      1. Sit behind this interface -- callers (src/review/workflow.py) never depend on
         a concrete provider.
      2. Keep a deterministic offline fallback available regardless
         (DeterministicReviewSummaryProvider remains usable on its own).
      3. Ground every statement in the supplied CaseResult/RiskAssessment evidence --
         never introduce a claim not traceable to those objects.
      4. Never invent facts. A statement that cannot be grounded in the supplied
         evidence must be omitted, not guessed at.
    """

    name: str

    @abstractmethod
    def summarize(self, case_result: CaseResult, risk_assessment: RiskAssessment) -> str:
        raise NotImplementedError


class DeterministicReviewSummaryProvider(ReviewSummaryProvider):
    """Composes an analyst-facing narrative entirely from already-computed,
    already-retained evidence (P1-P5 outputs). Deterministic given the same evidence."""

    name = "deterministic_offline_summary"

    def summarize(self, case_result: CaseResult, risk_assessment: RiskAssessment) -> str:
        doc_count = len(case_result.documents)
        doc_types = sorted({d.evidence.document_type.value for d in case_result.documents})
        parts = [
            f"Case {case_result.case_id}: {doc_count} document(s) ({', '.join(doc_types)}). "
            f"Policy outcome: {risk_assessment.policy_outcome} "
            f"(policy_version {risk_assessment.policy_version}).",
            risk_assessment.explanation,
        ]

        if case_result.identity_resolution.conflicts:
            parts.append("Identity conflicts: " + "; ".join(case_result.identity_resolution.conflicts))

        all_signals = [s for ds in case_result.fraud_assessment.document_signals for s in ds.signals]
        all_signals += case_result.fraud_assessment.case_level_signals
        if all_signals:
            parts.append(
                "Fraud signals: "
                + "; ".join(f"{s.category.value} ({s.severity.value})" for s in all_signals)
            )

        return " ".join(parts)
