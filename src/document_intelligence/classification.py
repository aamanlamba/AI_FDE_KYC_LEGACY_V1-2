from ..rules import PATTERNS
from .models import DocumentType

_DECLARED_MAP = {
    "PASSPORT": DocumentType.PASSPORT,
    "NATIONAL_ID": DocumentType.NATIONAL_ID,
    "DRIVING_LICENCE": DocumentType.DRIVING_LICENCE,
}


def _infer_from_document_number(document_number: str | None) -> DocumentType | None:
    if not document_number:
        return None
    for key, pattern in PATTERNS.items():
        if pattern.match(document_number):
            return DocumentType(key)
    return None


def classify_document(fields: dict, raw_text: str) -> tuple[DocumentType, float, list[str]]:
    """Classify a document from its parsed fields.

    Returns (document_type, classification_confidence, warnings). Confidence is a
    deterministic heuristic reflecting agreement between the declared label and the
    document-number format, not a calibrated probability.
    """
    warnings: list[str] = []
    declared = (fields.get("document_type") or "").strip().upper()
    inferred = _infer_from_document_number(fields.get("document_number"))

    if not declared:
        warnings.append("DOCUMENT_TYPE_DECLARATION_MISSING")
        if inferred is not None:
            return inferred, 0.55, warnings
        warnings.append("UNSUPPORTED_DOCUMENT_TYPE")
        return DocumentType.UNKNOWN, 0.0, warnings

    dtype = _DECLARED_MAP.get(declared)
    if dtype is None:
        warnings.append("UNSUPPORTED_DOCUMENT_TYPE")
        return DocumentType.UNKNOWN, 0.2, warnings

    if inferred is not None and inferred != dtype:
        warnings.append("DOCUMENT_TYPE_NUMBER_MISMATCH")
        return dtype, 0.6, warnings

    return dtype, 0.99, warnings
