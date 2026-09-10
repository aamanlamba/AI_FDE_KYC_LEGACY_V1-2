from enum import Enum

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    # Reserved specifically for capability-boundary honesty (e.g. checksum/signature
    # verification this system cannot genuinely perform on synthetic evidence). Distinct
    # from NOT_APPLICABLE, which means "this rule doesn't apply to this evidence" —
    # NOT_IMPLEMENTED means "this rule would apply in principle, but no implementation
    # exists, and we refuse to fabricate a PASS."
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationCategory(str, Enum):
    SCHEMA = "schema_validation"
    MANDATORY_FIELD = "mandatory_field_validation"
    DOCUMENT_NUMBER_FORMAT = "document_number_format_validation"
    DATE_FORMAT = "date_validation"
    TEMPORAL = "temporal_validation"
    EXPIRY = "expiry_validation"
    ISSUE_DATE_CONSISTENCY = "issue_date_consistency"
    CROSS_FIELD = "cross_field_validation"
    DOCUMENT_TYPE = "document_type_validation"
    CROSS_DOCUMENT_CONSISTENCY = "cross_document_consistency_validation"
    AUTHENTICITY_CHECKSUM = "authenticity_checksum_validation"


class ValidationResult(BaseModel):
    """One rule's outcome, fully traceable back to the evidence that produced it."""

    rule_id: str
    rule_version: str
    category: ValidationCategory
    status: ValidationStatus
    severity: Severity
    reason_code: str
    explanation: str
    evidence_references: list[str] = Field(default_factory=list)


class DocumentValidationReport(BaseModel):
    document_id: str
    reference_date: str
    results: list[ValidationResult]


class CaseValidationReport(BaseModel):
    case_id: str
    reference_date: str
    document_reports: list[DocumentValidationReport]
    case_level_results: list[ValidationResult]
