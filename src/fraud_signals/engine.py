from ..evidence_validation import CaseValidationReport, DocumentValidationReport
from ..evidence_validation.models import Severity
from ..identity_resolution import IdentityResolutionResult
from .models import DocumentFraudSignals, FraudAssessment, FraudAssessmentStatus
from .provider import DeterministicMarkerForensicsProvider, DocumentForensicsProvider
from .signals import (
    derive_document_duplication_signals,
    derive_extraction_inconsistency_signals,
    derive_identity_conflict_signals,
    derive_temporal_anomaly_signals,
)

_SEVERITY_RANK = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}


def _highest_severity(signals) -> Severity | None:
    if not signals:
        return None
    return max((s.severity for s in signals), key=lambda sev: _SEVERITY_RANK[sev])


def assess_document_fraud_signals(
    document_id: str,
    raw_text: str,
    evidence_reference: str,
    validation_report: DocumentValidationReport,
    forensics_provider: DocumentForensicsProvider | None = None,
) -> DocumentFraudSignals:
    provider = forensics_provider or DeterministicMarkerForensicsProvider()
    signals = [
        *provider.scan(document_id, raw_text, evidence_reference),
        *derive_temporal_anomaly_signals(validation_report),
        *derive_extraction_inconsistency_signals(validation_report),
    ]
    return DocumentFraudSignals(document_id=document_id, signals=signals)


def assess_case_fraud(
    case_id: str,
    document_signals: list[DocumentFraudSignals],
    identity_resolution: IdentityResolutionResult,
    case_validation_report: CaseValidationReport,
) -> FraudAssessment:
    case_level_signals = [
        *derive_identity_conflict_signals(identity_resolution),
        *derive_document_duplication_signals(case_validation_report),
    ]
    all_signals = [s for ds in document_signals for s in ds.signals] + case_level_signals

    # FRAUD_PROVEN is a reserved status (see FraudAssessmentStatus): no code path here
    # may set it. Fraud signals are evidence, separate from any final decision policy
    # (P5) and never a unilateral declaration that a document is fraudulent.
    status = FraudAssessmentStatus.FRAUD_SIGNAL_PRESENT if all_signals else FraudAssessmentStatus.NO_SIGNALS_DETECTED

    reason_codes = sorted({f"FRAUD_SIGNAL:{s.category.value}" for s in all_signals}) or ["NO_FRAUD_SIGNALS_DETECTED"]
    explanation = (
        f"{len(all_signals)} fraud signal(s) detected across {len(document_signals)} document(s)."
        if all_signals else
        "No fraud signals were detected from the available offline evidence."
    )
    return FraudAssessment(
        case_id=case_id,
        status=status,
        document_signals=document_signals,
        case_level_signals=case_level_signals,
        signal_count=len(all_signals),
        highest_severity=_highest_severity(all_signals),
        reason_codes=reason_codes,
        explanation=explanation,
    )
