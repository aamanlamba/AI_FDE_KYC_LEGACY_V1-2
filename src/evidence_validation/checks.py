from datetime import date

from ..document_intelligence import DocumentEvidence, DocumentQuality, DocumentType
from ..policy import MANDATORY_FIELDS, SUPPORTED_DOCUMENT_TYPES
from ..rules import PATTERNS
from .models import Severity, ValidationCategory, ValidationResult, ValidationStatus

RULE_VERSION = "1.0.0"

# Structural fact about each document type's schema, not a business policy value —
# kept alongside src.document_intelligence.sidecar_provider.FIELDS_BY_TYPE (same
# values) rather than imported from it, so this module can validate independently of
# whatever the extraction layer itself assumed (never trust extraction to prove itself).
_EXPECTED_FIELDS_BY_TYPE: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.PASSPORT: ("full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "nationality"),
    DocumentType.NATIONAL_ID: ("full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "address"),
    DocumentType.DRIVING_LICENCE: ("full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "address"),
}


def _result(
    rule_id: str,
    category: ValidationCategory,
    status: ValidationStatus,
    severity: Severity,
    reason_code: str,
    explanation: str,
    evidence_references: list[str],
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        category=category,
        status=status,
        severity=severity,
        reason_code=reason_code,
        explanation=explanation,
        evidence_references=evidence_references,
    )


def _safe_parse_date(value: str | None) -> date | None:
    """Never raises. A malformed date parses to None, it is never treated as valid."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def check_schema(evidence: DocumentEvidence) -> ValidationResult:
    rule_id = "SCHEMA-001"
    if evidence.document_type == DocumentType.UNKNOWN:
        return _result(
            rule_id, ValidationCategory.SCHEMA, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "SCHEMA_UNKNOWN_DOCUMENT_TYPE",
            "Document type is unknown/unsupported; there is no schema to validate evidence against.",
            [evidence.evidence_reference],
        )
    expected = set(_EXPECTED_FIELDS_BY_TYPE.get(evidence.document_type, ()))
    actual = set(evidence.fields)
    if expected == actual:
        return _result(
            rule_id, ValidationCategory.SCHEMA, ValidationStatus.PASS, Severity.HIGH,
            "SCHEMA_CONFORMS", f"Evidence field set matches the expected schema for {evidence.document_type.value}.",
            [evidence.evidence_reference],
        )
    return _result(
        rule_id, ValidationCategory.SCHEMA, ValidationStatus.FAIL, Severity.HIGH,
        "SCHEMA_FIELD_SET_MISMATCH",
        f"Evidence fields {sorted(actual)} do not match the expected schema {sorted(expected)} "
        f"for {evidence.document_type.value}.",
        [evidence.evidence_reference],
    )


def check_mandatory_fields(evidence: DocumentEvidence) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    unreadable = evidence.quality == DocumentQuality.INCOMPLETE_UNREADABLE
    type_known = evidence.document_type != DocumentType.UNKNOWN

    for field_name in MANDATORY_FIELDS:
        rule_id = f"MANDATORY-{field_name.upper()}"
        if not type_known:
            results.append(_result(
                rule_id, ValidationCategory.MANDATORY_FIELD, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
                "MANDATORY_FIELD_UNKNOWN_TYPE",
                f"Cannot assess mandatory field '{field_name}': document type is unknown.",
                [evidence.evidence_reference],
            ))
            continue

        field = evidence.fields.get(field_name)
        if field is not None and field.value is not None:
            results.append(_result(
                rule_id, ValidationCategory.MANDATORY_FIELD, ValidationStatus.PASS, Severity.HIGH,
                "MANDATORY_FIELD_PRESENT", f"Mandatory field '{field_name}' is present in the extracted evidence.",
                [field.provenance],
            ))
        elif unreadable:
            # The document itself was too poor to trust an absence finding from.
            results.append(_result(
                rule_id, ValidationCategory.MANDATORY_FIELD, ValidationStatus.UNKNOWN, Severity.HIGH,
                "EVIDENCE_UNREADABLE_CANNOT_CONFIRM_FIELD_ABSENCE",
                f"Mandatory field '{field_name}' was not extracted, but evidence quality is "
                "incomplete/unreadable; true absence cannot be confirmed.",
                [evidence.evidence_reference],
            ))
        else:
            results.append(_result(
                rule_id, ValidationCategory.MANDATORY_FIELD, ValidationStatus.FAIL, Severity.HIGH,
                "MANDATORY_FIELD_MISSING", f"Mandatory field '{field_name}' was not found in the extracted evidence.",
                [evidence.evidence_reference],
            ))
    return results


def check_document_number_format(evidence: DocumentEvidence) -> ValidationResult:
    rule_id = "DOCNUM-FORMAT"
    if evidence.document_type == DocumentType.UNKNOWN:
        return _result(
            rule_id, ValidationCategory.DOCUMENT_NUMBER_FORMAT, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "DOCNUM_UNKNOWN_TYPE", "Cannot validate document-number format: document type is unknown.",
            [evidence.evidence_reference],
        )
    field = evidence.fields.get("document_number")
    if field is None or field.value is None:
        return _result(
            rule_id, ValidationCategory.DOCUMENT_NUMBER_FORMAT, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "DOCNUM_NOT_EXTRACTED", "Cannot validate document-number format: no document number was extracted.",
            [evidence.evidence_reference],
        )
    pattern = PATTERNS.get(evidence.document_type.value)
    if pattern is None:
        return _result(
            rule_id, ValidationCategory.DOCUMENT_NUMBER_FORMAT, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "DOCNUM_NO_PATTERN_DEFINED", f"No document-number format is defined for {evidence.document_type.value}.",
            [field.provenance],
        )
    if pattern.match(field.value):
        return _result(
            rule_id, ValidationCategory.DOCUMENT_NUMBER_FORMAT, ValidationStatus.PASS, Severity.MEDIUM,
            "DOCNUM_FORMAT_VALID",
            f"Document number '{field.value}' matches the expected format for {evidence.document_type.value}.",
            [field.provenance],
        )
    return _result(
        rule_id, ValidationCategory.DOCUMENT_NUMBER_FORMAT, ValidationStatus.FAIL, Severity.MEDIUM,
        "DOCNUM_FORMAT_INVALID",
        f"Document number '{field.value}' does not match the expected format for {evidence.document_type.value}.",
        [field.provenance],
    )


def check_date_format(evidence: DocumentEvidence, field_name: str) -> ValidationResult:
    rule_id = f"DATE-FORMAT-{field_name.upper()}"
    field = evidence.fields.get(field_name)
    if field is None or field.value is None:
        return _result(
            rule_id, ValidationCategory.DATE_FORMAT, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "DATE_NOT_EXTRACTED", f"Cannot validate date format: '{field_name}' was not extracted.",
            [evidence.evidence_reference],
        )
    if _safe_parse_date(field.value) is not None:
        return _result(
            rule_id, ValidationCategory.DATE_FORMAT, ValidationStatus.PASS, Severity.MEDIUM,
            "DATE_FORMAT_VALID", f"'{field_name}' value '{field.value}' is a valid ISO calendar date.",
            [field.provenance],
        )
    # A malformed date is a FAIL here, and never silently treated as evidence of validity
    # by any downstream rule (see check_temporal_issue_not_future / check_expiry_not_past,
    # which report NOT_APPLICABLE rather than PASS when the date fails to parse).
    return _result(
        rule_id, ValidationCategory.DATE_FORMAT, ValidationStatus.FAIL, Severity.MEDIUM,
        "DATE_FORMAT_INVALID", f"'{field_name}' value '{field.value}' could not be parsed as an ISO calendar date.",
        [field.provenance],
    )


def check_temporal_issue_not_future(evidence: DocumentEvidence, reference_date: date) -> ValidationResult:
    rule_id = "TEMPORAL-ISSUE-NOT-FUTURE"
    field = evidence.fields.get("issue_date")
    if field is None or field.value is None:
        return _result(
            rule_id, ValidationCategory.TEMPORAL, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "ISSUE_DATE_NOT_EXTRACTED", "Cannot assess temporal validity: issue_date was not extracted.",
            [evidence.evidence_reference],
        )
    parsed = _safe_parse_date(field.value)
    if parsed is None:
        return _result(
            rule_id, ValidationCategory.TEMPORAL, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "ISSUE_DATE_MALFORMED",
            "Cannot assess temporal validity: issue_date is not a valid date (see DATE-FORMAT-ISSUE_DATE).",
            [field.provenance],
        )
    if parsed <= reference_date:
        return _result(
            rule_id, ValidationCategory.TEMPORAL, ValidationStatus.PASS, Severity.MEDIUM,
            "ISSUE_DATE_NOT_IN_FUTURE",
            f"issue_date {parsed.isoformat()} is not after the reference date {reference_date.isoformat()}.",
            [field.provenance],
        )
    return _result(
        rule_id, ValidationCategory.TEMPORAL, ValidationStatus.FAIL, Severity.MEDIUM,
        "ISSUE_DATE_IN_FUTURE",
        f"issue_date {parsed.isoformat()} is after the reference date {reference_date.isoformat()}.",
        [field.provenance],
    )


def check_expiry_not_past(evidence: DocumentEvidence, reference_date: date) -> ValidationResult:
    rule_id = "EXPIRY-NOT-PAST"
    field = evidence.fields.get("expiry_date")
    if field is None or field.value is None:
        return _result(
            rule_id, ValidationCategory.EXPIRY, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "EXPIRY_DATE_NOT_EXTRACTED", "Cannot assess expiry: expiry_date was not extracted.",
            [evidence.evidence_reference],
        )
    parsed = _safe_parse_date(field.value)
    if parsed is None:
        return _result(
            rule_id, ValidationCategory.EXPIRY, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "EXPIRY_DATE_MALFORMED",
            "Cannot assess expiry: expiry_date is not a valid date (see DATE-FORMAT-EXPIRY_DATE).",
            [field.provenance],
        )
    if parsed >= reference_date:
        return _result(
            rule_id, ValidationCategory.EXPIRY, ValidationStatus.PASS, Severity.HIGH,
            "NOT_EXPIRED",
            f"expiry_date {parsed.isoformat()} is on or after the reference date {reference_date.isoformat()}.",
            [field.provenance],
        )
    return _result(
        rule_id, ValidationCategory.EXPIRY, ValidationStatus.FAIL, Severity.HIGH,
        "DOCUMENT_EXPIRED",
        f"expiry_date {parsed.isoformat()} is before the reference date {reference_date.isoformat()}.",
        [field.provenance],
    )


def check_issue_before_expiry(evidence: DocumentEvidence) -> ValidationResult:
    rule_id = "ISSUEDATE-BEFORE-EXPIRY"
    issue_field = evidence.fields.get("issue_date")
    expiry_field = evidence.fields.get("expiry_date")
    if issue_field is None or issue_field.value is None or expiry_field is None or expiry_field.value is None:
        return _result(
            rule_id, ValidationCategory.ISSUE_DATE_CONSISTENCY, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "ISSUE_OR_EXPIRY_NOT_EXTRACTED",
            "Cannot assess issue/expiry consistency: one or both dates were not extracted.",
            [evidence.evidence_reference],
        )
    issue, expiry = _safe_parse_date(issue_field.value), _safe_parse_date(expiry_field.value)
    if issue is None or expiry is None:
        return _result(
            rule_id, ValidationCategory.ISSUE_DATE_CONSISTENCY, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "ISSUE_OR_EXPIRY_MALFORMED", "Cannot assess issue/expiry consistency: one or both dates are malformed.",
            [issue_field.provenance, expiry_field.provenance],
        )
    if issue < expiry:
        return _result(
            rule_id, ValidationCategory.ISSUE_DATE_CONSISTENCY, ValidationStatus.PASS, Severity.HIGH,
            "ISSUE_BEFORE_EXPIRY", f"issue_date {issue.isoformat()} precedes expiry_date {expiry.isoformat()}.",
            [issue_field.provenance, expiry_field.provenance],
        )
    return _result(
        rule_id, ValidationCategory.ISSUE_DATE_CONSISTENCY, ValidationStatus.FAIL, Severity.HIGH,
        "ISSUE_NOT_BEFORE_EXPIRY",
        f"issue_date {issue.isoformat()} does not precede expiry_date {expiry.isoformat()}.",
        [issue_field.provenance, expiry_field.provenance],
    )


def check_dob_before_issue(evidence: DocumentEvidence) -> ValidationResult:
    rule_id = "DOB-BEFORE-ISSUE"
    dob_field = evidence.fields.get("date_of_birth")
    issue_field = evidence.fields.get("issue_date")
    if dob_field is None or dob_field.value is None or issue_field is None or issue_field.value is None:
        return _result(
            rule_id, ValidationCategory.CROSS_FIELD, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "DOB_OR_ISSUE_NOT_EXTRACTED",
            "Cannot assess date-of-birth/issue-date consistency: one or both were not extracted.",
            [evidence.evidence_reference],
        )
    dob, issue = _safe_parse_date(dob_field.value), _safe_parse_date(issue_field.value)
    if dob is None or issue is None:
        return _result(
            rule_id, ValidationCategory.CROSS_FIELD, ValidationStatus.NOT_APPLICABLE, Severity.INFO,
            "DOB_OR_ISSUE_MALFORMED",
            "Cannot assess date-of-birth/issue-date consistency: one or both dates are malformed.",
            [dob_field.provenance, issue_field.provenance],
        )
    if dob < issue:
        return _result(
            rule_id, ValidationCategory.CROSS_FIELD, ValidationStatus.PASS, Severity.MEDIUM,
            "DOB_BEFORE_ISSUE", f"date_of_birth {dob.isoformat()} precedes issue_date {issue.isoformat()}.",
            [dob_field.provenance, issue_field.provenance],
        )
    return _result(
        rule_id, ValidationCategory.CROSS_FIELD, ValidationStatus.FAIL, Severity.MEDIUM,
        "DOB_NOT_BEFORE_ISSUE",
        f"date_of_birth {dob.isoformat()} does not precede issue_date {issue.isoformat()}.",
        [dob_field.provenance, issue_field.provenance],
    )


def check_document_type_supported(evidence: DocumentEvidence) -> ValidationResult:
    rule_id = "DOCTYPE-SUPPORTED"
    if evidence.document_type.value in SUPPORTED_DOCUMENT_TYPES:
        return _result(
            rule_id, ValidationCategory.DOCUMENT_TYPE, ValidationStatus.PASS, Severity.HIGH,
            "DOCUMENT_TYPE_SUPPORTED", f"Document type '{evidence.document_type.value}' is a supported type.",
            [evidence.evidence_reference],
        )
    return _result(
        rule_id, ValidationCategory.DOCUMENT_TYPE, ValidationStatus.FAIL, Severity.HIGH,
        "DOCUMENT_TYPE_UNSUPPORTED",
        f"Document type '{evidence.document_type.value}' is not in the supported set "
        f"{sorted(SUPPORTED_DOCUMENT_TYPES)}.",
        [evidence.evidence_reference],
    )


def check_checksum_signature(evidence: DocumentEvidence) -> ValidationResult:
    """Honest capability-boundary disclosure (see ValidationStatus.NOT_IMPLEMENTED)."""
    return _result(
        "CHECKSUM-SIGNATURE", ValidationCategory.AUTHENTICITY_CHECKSUM, ValidationStatus.NOT_IMPLEMENTED,
        Severity.INFO, "CHECKSUM_CAPABILITY_NOT_IMPLEMENTED",
        "This system has no cryptographic checksum/signature verification capability over "
        "synthetic evidence. This is a disclosed capability boundary, not a passed or failed check.",
        [evidence.evidence_reference],
    )
