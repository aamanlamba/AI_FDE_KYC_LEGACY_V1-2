from .ingestion import DocumentIngestionSource, SidecarIngestionSource
from .models import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField, IngestedDocument
from .provider import DocumentIntelligenceProvider, ProviderContractError, extract_evidence
from .sidecar_provider import DeterministicSidecarProvider

_default_provider = DeterministicSidecarProvider()


def get_default_provider() -> DocumentIntelligenceProvider:
    """The offline, deterministic default provider used by the running service."""
    return _default_provider


__all__ = [
    "DocumentType",
    "DocumentQuality",
    "EvidenceField",
    "DocumentEvidence",
    "IngestedDocument",
    "DocumentIntelligenceProvider",
    "ProviderContractError",
    "extract_evidence",
    "DeterministicSidecarProvider",
    "DocumentIngestionSource",
    "SidecarIngestionSource",
    "get_default_provider",
]
