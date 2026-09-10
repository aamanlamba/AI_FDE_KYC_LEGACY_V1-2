from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    PASSPORT = "passport"
    NATIONAL_ID = "national_id"
    DRIVING_LICENCE = "driving_licence"
    UNKNOWN = "unknown"


class DocumentQuality(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    ROTATED = "rotated"
    INCOMPLETE_UNREADABLE = "incomplete_unreadable"


class EvidenceField(BaseModel):
    """A single extracted field with its own confidence, provenance and warnings.

    Missing evidence is represented explicitly (value=None, confidence=0.0,
    warnings=['FIELD_NOT_FOUND']) rather than omitted or fabricated.
    """

    value: str | None = None
    normalized_value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    provenance: str
    warnings: list[str] = Field(default_factory=list)


class DocumentEvidence(BaseModel):
    """The validated, provider-agnostic output contract of the document-processing boundary."""

    document_id: str
    document_type: DocumentType
    fields: dict[str, EvidenceField]
    quality: DocumentQuality
    extraction_warnings: list[str] = Field(default_factory=list)
    provider: str
    evidence_reference: str


class IngestedDocument(BaseModel):
    """Internal ingestion result. Never serialized directly onto an API response."""

    document_id: str
    raw_text: str
    source_reference: str
    image_reference: str
