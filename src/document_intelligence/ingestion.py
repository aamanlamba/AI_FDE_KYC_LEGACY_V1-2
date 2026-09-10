from abc import ABC, abstractmethod

from ..ocr import extract_text
from .models import IngestedDocument


class DocumentIngestionSource(ABC):
    """Abstraction over how raw document evidence is obtained for a document_id.

    A future real-OCR/VLM provider would supply its own ingestion source (e.g. one
    that fetches image bytes and calls an external service) without requiring any
    change to classification, quality assessment or downstream business logic.
    """

    @abstractmethod
    def ingest(self, document_id: str) -> IngestedDocument:
        raise NotImplementedError


class SidecarIngestionSource(DocumentIngestionSource):
    """Offline ingestion: reads the deterministic OCR sidecar text file."""

    def ingest(self, document_id: str) -> IngestedDocument:
        raw_text = extract_text(document_id)
        return IngestedDocument(
            document_id=document_id,
            raw_text=raw_text,
            source_reference=f"data/sidecar_ocr/{document_id}.txt",
            image_reference=f"data/input_documents/{document_id}.png",
        )
