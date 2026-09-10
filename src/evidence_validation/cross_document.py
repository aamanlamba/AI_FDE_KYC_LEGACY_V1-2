from collections import Counter

from ..document_intelligence import DocumentEvidence, DocumentType
from .models import Severity, ValidationCategory, ValidationResult, ValidationStatus

RULE_VERSION = "1.0.0"


def check_no_duplicate_document_type(documents_evidence: list[DocumentEvidence]) -> ValidationResult:
    """A distinct, structural cross-document check: two documents of the same
    classified type in one case is a computable anomaly. This is independent of
    src.identity_resolution, which compares attribute VALUES (name/DOB/address)
    across documents; this checks document-type STRUCTURE instead.
    """
    rule_id = "CROSSDOC-NO-DUPLICATE-TYPE"
    references = [e.evidence_reference for e in documents_evidence]
    known_types = [e.document_type for e in documents_evidence if e.document_type != DocumentType.UNKNOWN]
    duplicates = {dtype: count for dtype, count in Counter(known_types).items() if count > 1}

    if not duplicates:
        return ValidationResult(
            rule_id=rule_id, rule_version=RULE_VERSION, category=ValidationCategory.CROSS_DOCUMENT_CONSISTENCY,
            status=ValidationStatus.PASS, severity=Severity.MEDIUM, reason_code="NO_DUPLICATE_DOCUMENT_TYPES",
            explanation="No two documents in this case share the same classified document type.",
            evidence_references=references,
        )
    description = ", ".join(f"{dtype.value}x{count}" for dtype, count in duplicates.items())
    return ValidationResult(
        rule_id=rule_id, rule_version=RULE_VERSION, category=ValidationCategory.CROSS_DOCUMENT_CONSISTENCY,
        status=ValidationStatus.FAIL, severity=Severity.MEDIUM, reason_code="DUPLICATE_DOCUMENT_TYPES",
        explanation=f"Multiple documents in this case share the same classified document type: {description}.",
        evidence_references=references,
    )
