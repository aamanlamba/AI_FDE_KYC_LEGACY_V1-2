"""DecisionLineage: the single object an auditor reads to reconstruct a decision
without reading source code (P9 requirement 9 and success criteria).

Every piece of a lineage record is already computed and retained elsewhere on
CaseResult (risk_assessment, validation, fraud_assessment, identity_resolution) --
this module does not recompute anything. It exists to add the two things that were
NOT previously captured anywhere on the result: which trace this decision was computed
under, and which exact version of each component produced it (src.observability.versions).
"""

from pydantic import BaseModel, Field

from ..decision_policy import RiskAssessment
from .context import TraceContext
from .versions import component_versions


class DecisionLineage(BaseModel):
    trace_id: str
    case_id: str
    decision: str
    policy_version: str
    component_versions: dict[str, str]
    risk_factor_summary: list[str] = Field(default_factory=list)
    evidence_reference_count: int


def build_decision_lineage(
    case_id: str, decision: str, risk_assessment: RiskAssessment, trace_context: TraceContext
) -> DecisionLineage:
    evidence_reference_count = sum(len(factor.evidence_references) for factor in risk_assessment.risk_factors)
    risk_factor_summary = [
        f"{factor.factor_id} ({factor.category.value}, {factor.severity.value}"
        f"{', hard-stop' if factor.triggers_hard_stop else ''})"
        for factor in risk_assessment.risk_factors
    ]
    return DecisionLineage(
        trace_id=trace_context.trace_id,
        case_id=case_id,
        decision=decision,
        policy_version=risk_assessment.policy_version,
        component_versions=component_versions(),
        risk_factor_summary=risk_factor_summary,
        evidence_reference_count=evidence_reference_count,
    )
