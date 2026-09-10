from .engine import assess_case_fraud, assess_document_fraud_signals
from .models import DocumentFraudSignals, FraudAssessment, FraudAssessmentStatus, FraudCategory, FraudSignal
from .provider import DeterministicMarkerForensicsProvider, DocumentForensicsProvider

_default_forensics_provider = DeterministicMarkerForensicsProvider()


def get_default_forensics_provider() -> DocumentForensicsProvider:
    return _default_forensics_provider


__all__ = [
    "FraudCategory",
    "FraudAssessmentStatus",
    "FraudSignal",
    "DocumentFraudSignals",
    "FraudAssessment",
    "DocumentForensicsProvider",
    "DeterministicMarkerForensicsProvider",
    "get_default_forensics_provider",
    "assess_document_fraud_signals",
    "assess_case_fraud",
]
