from enum import Enum

from pydantic import BaseModel, Field

from ..document_intelligence import DocumentEvidence
from ..evidence_validation.models import CaseValidationReport, DocumentValidationReport, Severity
from ..fraud_signals import DocumentFraudSignals, FraudAssessment
from ..identity_resolution import IdentityResolutionResult
from ..policy import Decision


class RiskFactorCategory(str, Enum):
    DOCUMENT_DECISION = "document_decision"
    IDENTITY_CONFLICT = "identity_conflict"
    IDENTITY_UNCERTAINTY = "identity_uncertainty"
    FRAUD_SIGNAL = "fraud_signal"
    VALIDATION_FAILURE = "validation_failure"
    EVIDENCE_QUALITY = "evidence_quality"


class RiskFactor(BaseModel):
    """One inspectable contributor to the policy outcome. The policy decision is the
    union of these factors' triggers_hard_stop flags — never an opaque score."""

    factor_id: str
    category: RiskFactorCategory
    severity: Severity
    triggers_hard_stop: bool
    description: str
    source: str
    evidence_references: list[str] = Field(default_factory=list)


class DocumentEvidenceSummary(BaseModel):
    """The subset of a document's already-computed results the policy engine needs.
    Deliberately not the full DocumentResult (which lives in src.models) to avoid a
    circular import — src.models needs RiskAssessment, so decision_policy cannot
    depend on src.models."""

    document_id: str
    legacy_decision: Decision
    legacy_reason_codes: list[str]
    evidence: DocumentEvidence
    validation: DocumentValidationReport
    fraud_signals: DocumentFraudSignals


class EvidenceBundle(BaseModel):
    """All case evidence the policy engine may consider. Not duplicated onto the API
    response: every constituent piece is already independently retained on CaseResult
    (documents[*].evidence/validation/fraud_signals, identity_resolution, validation,
    fraud_assessment) — see docs/data_dictionary.md for the reproducibility argument."""

    case_id: str
    documents: list[DocumentEvidenceSummary]
    identity_resolution: IdentityResolutionResult
    case_validation: CaseValidationReport
    fraud_assessment: FraudAssessment


class RiskAssessment(BaseModel):
    case_id: str
    policy_version: str
    risk_factors: list[RiskFactor]
    evidence_strength: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    validation_failure_count: int
    identity_conflict_count: int
    fraud_signal_count: int
    hard_stop_triggered: bool
    policy_outcome: Decision
    reason_codes: list[str]
    explanation: str
