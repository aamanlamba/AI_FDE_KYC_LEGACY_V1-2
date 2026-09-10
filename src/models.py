from typing import Literal, Any
from pydantic import BaseModel, Field

from .document_intelligence import DocumentEvidence
from .identity_resolution import IdentityResolutionResult
from .evidence_validation import DocumentValidationReport, CaseValidationReport

Decision = Literal["APPROVE","REVIEW","REJECT"]

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

class CaseResult(BaseModel):
    case_id: str
    decision: Decision
    reason_codes: list[str]
    documents: list[DocumentResult]
    limitation_notice: str
    identity_resolution: IdentityResolutionResult
    validation: CaseValidationReport
