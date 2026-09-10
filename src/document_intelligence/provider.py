from abc import ABC, abstractmethod

from .models import DocumentEvidence


class ProviderContractError(RuntimeError):
    """Raised when a Document Intelligence provider does not honour the DocumentEvidence contract."""


class DocumentIntelligenceProvider(ABC):
    """Provider interface for document evidence extraction.

    Any implementation — the deterministic offline sidecar provider today, or a real
    OCR/VLM/layout provider later — must return a schema-validated DocumentEvidence.
    Callers (src/service.py) depend only on this interface, never on a concrete
    provider, so providers can be swapped without changing downstream business logic.
    """

    name: str

    @abstractmethod
    def extract(self, document_id: str) -> DocumentEvidence:
        raise NotImplementedError


def extract_evidence(provider: DocumentIntelligenceProvider, document_id: str) -> DocumentEvidence:
    """Call a provider and enforce its contract before evidence reaches downstream code."""
    result = provider.extract(document_id)
    if not isinstance(result, DocumentEvidence):
        provider_name = getattr(provider, "name", provider.__class__.__name__)
        raise ProviderContractError(
            f"provider '{provider_name}' returned {type(result).__name__}, expected DocumentEvidence"
        )
    return result
