import re
from datetime import date

from ..parser import parse_legacy_ocr
from ..rules import PATTERNS as _DOCUMENT_NUMBER_PATTERNS
from .classification import classify_document
from .ingestion import DocumentIngestionSource, SidecarIngestionSource
from .models import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
from .provider import DocumentIntelligenceProvider
from .quality import assess_quality

CANONICAL_FIELDS = (
    "full_name",
    "date_of_birth",
    "document_number",
    "issue_date",
    "expiry_date",
    "address",
    "nationality",
)
DATE_FIELDS = {"date_of_birth", "issue_date", "expiry_date"}

FIELDS_BY_TYPE: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.PASSPORT: ("full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "nationality"),
    DocumentType.NATIONAL_ID: ("full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "address"),
    DocumentType.DRIVING_LICENCE: ("full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "address"),
}

BASE_CONFIDENCE_BY_QUALITY = {
    DocumentQuality.NORMAL: 0.97,
    DocumentQuality.DEGRADED: 0.75,
    DocumentQuality.ROTATED: 0.80,
    DocumentQuality.INCOMPLETE_UNREADABLE: 0.30,
}


def _normalize(field_name: str, value: str) -> str | None:
    """Deterministic, content-preserving normalization only. Never corrects OCR errors."""
    if field_name in DATE_FIELDS:
        try:
            date.fromisoformat(value)
            return value
        except ValueError:
            return None
    if field_name == "document_number":
        return value.strip().upper()
    return re.sub(r"\s+", " ", value).strip()


def build_document_evidence(
    document_id: str, raw_text: str, provider_name: str, evidence_reference: str
) -> DocumentEvidence:
    """Pure function: raw sidecar text -> validated DocumentEvidence. No I/O."""
    fields, parse_warnings = parse_legacy_ocr(raw_text)
    dtype, _classification_confidence, class_warnings = classify_document(fields, raw_text)

    present_count = sum(1 for name in CANONICAL_FIELDS if fields.get(name))
    expected = FIELDS_BY_TYPE.get(dtype, ())
    quality, quality_warnings = assess_quality(raw_text, present_count, len(expected))
    base_confidence = BASE_CONFIDENCE_BY_QUALITY[quality]

    # Unknown/unsupported types: report only fields actually found, never presumed.
    field_names = expected or tuple(name for name in CANONICAL_FIELDS if fields.get(name))

    evidence_fields: dict[str, EvidenceField] = {}
    for name in field_names:
        raw_value = fields.get(name)
        if not raw_value:
            evidence_fields[name] = EvidenceField(
                value=None,
                normalized_value=None,
                confidence=0.0,
                source=provider_name,
                provenance=evidence_reference,
                warnings=["FIELD_NOT_FOUND"],
            )
            continue

        normalized = _normalize(name, raw_value)
        field_warnings: list[str] = []
        confidence = base_confidence

        if name in DATE_FIELDS and normalized is None:
            field_warnings.append("FIELD_FORMAT_INVALID")
            confidence = min(confidence, 0.4)
        if name == "document_number" and dtype != DocumentType.UNKNOWN:
            pattern = _DOCUMENT_NUMBER_PATTERNS.get(dtype.value)
            if pattern is not None and not pattern.match(raw_value):
                field_warnings.append("FIELD_FORMAT_INVALID")
                confidence = min(confidence, 0.4)

        evidence_fields[name] = EvidenceField(
            value=raw_value,
            normalized_value=normalized,
            confidence=round(confidence, 3),
            source=provider_name,
            provenance=f"{evidence_reference}#field={name}",
            warnings=field_warnings,
        )

    extraction_warnings = [*parse_warnings, *class_warnings, *quality_warnings]
    return DocumentEvidence(
        document_id=document_id,
        document_type=dtype,
        fields=evidence_fields,
        quality=quality,
        extraction_warnings=extraction_warnings,
        provider=provider_name,
        evidence_reference=evidence_reference,
    )


class DeterministicSidecarProvider(DocumentIntelligenceProvider):
    """Offline provider: wraps the existing deterministic sidecar OCR + legacy parser."""

    name = "deterministic_sidecar_ocr"

    def __init__(self, ingestion_source: DocumentIngestionSource | None = None):
        self._ingestion_source = ingestion_source or SidecarIngestionSource()

    def extract(self, document_id: str) -> DocumentEvidence:
        ingested = self._ingestion_source.ingest(document_id)
        return build_document_evidence(
            document_id=ingested.document_id,
            raw_text=ingested.raw_text,
            provider_name=self.name,
            evidence_reference=ingested.source_reference,
        )
