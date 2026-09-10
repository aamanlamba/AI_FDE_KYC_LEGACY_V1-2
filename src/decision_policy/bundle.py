from ..evidence_validation.models import CaseValidationReport
from ..fraud_signals import FraudAssessment
from ..identity_resolution import IdentityResolutionResult
from .models import DocumentEvidenceSummary, EvidenceBundle


def build_evidence_bundle(
    case_id: str,
    document_summaries: list[DocumentEvidenceSummary],
    identity_resolution: IdentityResolutionResult,
    case_validation: CaseValidationReport,
    fraud_assessment: FraudAssessment,
) -> EvidenceBundle:
    """Pure aggregation — every input is already computed by src.service.verify_case;
    nothing here recomputes any prior stage's evidence."""
    return EvidenceBundle(
        case_id=case_id,
        documents=document_summaries,
        identity_resolution=identity_resolution,
        case_validation=case_validation,
        fraud_assessment=fraud_assessment,
    )
