from abc import ABC, abstractmethod

from .models import FraudSignal
from .registry import KNOWN_SIDECAR_ANOMALY_MARKERS


class DocumentForensicsProvider(ABC):
    """Interface for a document-forensics fraud-signal source.

    Today's only implementation (DeterministicMarkerForensicsProvider) can detect known
    literal text markers in the deterministic OCR sidecar. It performs NO pixel-level
    image analysis: this repository's extraction layer never reads image pixels at all
    (see docs/assessment/architecture_current.md, confirmed by grep — no module under
    src/ opens the PNG evidence images). This class exists so a future real forensics
    provider (image manipulation detection, metadata/EXIF analysis, cryptographic
    signature checks) can be plugged in without changing any downstream consumer of
    FraudSignal.

    Requirements this interface enforces by construction:
      - Any implementation must be grounded in real, executable, testable algorithms —
        never an LLM's free-text assertion that a document "looks fraudulent."
      - No implementation may call an LLM (or any other opaque judgment source) to
        reach a fraud conclusion. scan() returns evidence (FraudSignal), never a
        verdict; verdicts are out of scope for this interface entirely.
    """

    name: str

    @abstractmethod
    def scan(self, document_id: str, raw_text: str, evidence_reference: str) -> list[FraudSignal]:
        raise NotImplementedError


class DeterministicMarkerForensicsProvider(DocumentForensicsProvider):
    """Offline provider: literal substring scan against a small, honest marker registry."""

    name = "deterministic_marker_forensics"

    def scan(self, document_id: str, raw_text: str, evidence_reference: str) -> list[FraudSignal]:
        signals: list[FraudSignal] = []
        for marker, (category, severity, reason_code, explanation) in KNOWN_SIDECAR_ANOMALY_MARKERS.items():
            if marker in raw_text:
                signals.append(FraudSignal(
                    signal_id=f"{document_id}:{reason_code}",
                    category=category,
                    severity=severity,
                    confidence=None,  # a literal marker match is a binary fact, not a probability
                    source=f"{self.name}:sidecar_text_substring_match",
                    supporting_evidence=[evidence_reference],
                    explanation=explanation,
                ))
        return signals
