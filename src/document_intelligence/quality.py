from .models import DocumentQuality


def assess_quality(
    raw_text: str, present_field_count: int, expected_field_count: int
) -> tuple[DocumentQuality, list[str]]:
    """Assess capture/extraction quality from raw evidence text and field yield.

    This assesses capture-condition and completeness signals only. It deliberately
    does not evaluate authenticity/tampering — that remains a decisioning concern
    (src/rules.py) and is out of scope for this stage.
    """
    warnings: list[str] = []

    if not raw_text.strip():
        return DocumentQuality.INCOMPLETE_UNREADABLE, ["EVIDENCE_UNREADABLE"]

    degraded = "OCR_QUALITY: DEGRADED" in raw_text
    rotated = "CAPTURE_ORIENTATION: 90_DEGREES" in raw_text
    if degraded:
        warnings.append("OCR_QUALITY_DEGRADED")
    if rotated:
        warnings.append("CAPTURE_ORIENTATION_ROTATED")

    if expected_field_count and (present_field_count / expected_field_count) < 0.5:
        warnings.append("EVIDENCE_INCOMPLETE")
        return DocumentQuality.INCOMPLETE_UNREADABLE, warnings

    if degraded:
        return DocumentQuality.DEGRADED, warnings
    if rotated:
        return DocumentQuality.ROTATED, warnings
    return DocumentQuality.NORMAL, warnings
