from typing import Any
from pydantic import BaseModel, Field

from .document_intelligence import DocumentEvidence
from .identity_resolution import IdentityResolutionResult
from .evidence_validation import DocumentValidationReport, CaseValidationReport
from .fraud_signals import DocumentFraudSignals, FraudAssessment
from .decision_policy import RiskAssessment
from .policy import Decision

class VerifyDocumentRequest(BaseModel):
    document_id: str = Field(min_length=3, max_length=80)

class DocumentResult(BaseModel):
    document_id: str
    document_type: str | None = None
    decision: Decision
    reason_codes: list[str]
    parsed_fields: dict[str, Any]
    completeness: float
    warnings: list[str]
    source: str = "deterministic_sidecar_ocr"
    evidence: DocumentEvidence
    validation: DocumentValidationReport
    fraud_signals: DocumentFraudSignals

class CaseResult(BaseModel):
    case_id: str
    decision: Decision
    reason_codes: list[str]
    documents: list[DocumentResult]
    limitation_notice: str
    identity_resolution: IdentityResolutionResult
    validation: CaseValidationReport
    fraud_assessment: FraudAssessment
    risk_assessment: RiskAssessment
