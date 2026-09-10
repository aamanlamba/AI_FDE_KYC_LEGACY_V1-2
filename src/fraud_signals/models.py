from enum import Enum

from pydantic import BaseModel, Field

from ..evidence_validation.models import Severity


class FraudCategory(str, Enum):
    TAMPER_MARKER = "tamper_marker"
    FIELD_INCONSISTENCY = "field_inconsistency"
    TEMPORAL_ANOMALY = "temporal_anomaly"
    EXTRACTION_INCONSISTENCY = "extraction_inconsistency"
    IDENTITY_CONFLICT = "identity_conflict"
    DOCUMENT_DUPLICATION = "document_duplication"
    # Reserved for a sidecar anomaly marker not covered by a more specific category
    # above. Currently unused: the only anomaly marker present in this training
    # dataset (the tamper fixture) already has its own specific category. Kept in the
    # type system so the marker-registry mechanism (src/fraud_signals/registry.py)
    # generalizes to future markers without a schema change.
    SIDECAR_METADATA_ANOMALY = "sidecar_metadata_anomaly"


class FraudAssessmentStatus(str, Enum):
    NO_SIGNALS_DETECTED = "NO_SIGNALS_DETECTED"
    FRAUD_SIGNAL_PRESENT = "FRAUD_SIGNAL_PRESENT"
    # Reserved. No code path in this repository may produce this status: proving fraud
    # requires evidence (corroborated investigation, cryptographic verification, a
    # confirmed forensic match) that this offline, deterministic signal set cannot
    # produce. See src/fraud_signals/provider.py and src/fraud_signals/engine.py.
    FRAUD_PROVEN = "FRAUD_PROVEN"


class FraudSignal(BaseModel):
    """One piece of fraud-relevant evidence. A signal, never a verdict."""

    signal_id: str
    category: FraudCategory
    severity: Severity
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str
    supporting_evidence: list[str] = Field(default_factory=list)
    explanation: str


class DocumentFraudSignals(BaseModel):
    document_id: str
    signals: list[FraudSignal]


class FraudAssessment(BaseModel):
    """Aggregated fraud evidence for a case. Reporting only — see FraudAssessmentStatus
    for why FRAUD_PROVEN can never be produced here, and docs/data_dictionary.md for
    how this differs from src/rules.py's unchanged SUSPECTED_TAMPERING decision path.
    """

    case_id: str
    status: FraudAssessmentStatus
    document_signals: list[DocumentFraudSignals]
    case_level_signals: list[FraudSignal]
    signal_count: int
    highest_severity: Severity | None = None
    reason_codes: list[str]
    explanation: str
