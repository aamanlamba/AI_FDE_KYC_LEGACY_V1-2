from datetime import date

from ..document_intelligence import DocumentEvidence
from ..rules import REFERENCE_DATE as DEFAULT_REFERENCE_DATE
from . import checks
from .cross_document import check_no_duplicate_document_type
from .models import CaseValidationReport, DocumentValidationReport


def validate_document(evidence: DocumentEvidence, reference_date: date | None = None) -> DocumentValidationReport:
    """Run every document-level validation category against one document's evidence.

    reference_date defaults to the repository's frozen, reproducible reference date but
    is injectable (e.g. for boundary-date testing) without touching that default.
    """
    ref = reference_date or DEFAULT_REFERENCE_DATE
    results = [
        checks.check_schema(evidence),
        *checks.check_mandatory_fields(evidence),
        checks.check_document_number_format(evidence),
        checks.check_date_format(evidence, "date_of_birth"),
        checks.check_date_format(evidence, "issue_date"),
        checks.check_date_format(evidence, "expiry_date"),
        checks.check_temporal_issue_not_future(evidence, ref),
        checks.check_expiry_not_past(evidence, ref),
        checks.check_issue_before_expiry(evidence),
        checks.check_dob_before_issue(evidence),
        checks.check_document_type_supported(evidence),
        checks.check_checksum_signature(evidence),
    ]
    return DocumentValidationReport(document_id=evidence.document_id, reference_date=ref.isoformat(), results=results)


def validate_case(
    case_id: str,
    document_reports: list[DocumentValidationReport],
    documents_evidence: list[DocumentEvidence],
    reference_date: date | None = None,
) -> CaseValidationReport:
    """Combine already-computed document reports with case-level (cross-document) checks."""
    ref = reference_date or DEFAULT_REFERENCE_DATE
    case_level_results = [check_no_duplicate_document_type(documents_evidence)]
    return CaseValidationReport(
        case_id=case_id, reference_date=ref.isoformat(),
        document_reports=document_reports, case_level_results=case_level_results,
    )
