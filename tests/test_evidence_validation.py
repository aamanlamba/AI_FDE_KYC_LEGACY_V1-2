from datetime import date

from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
from src.evidence_validation import ValidationStatus, validate_document
from src.evidence_validation.checks import (
    check_checksum_signature,
    check_date_format,
    check_document_type_supported,
    check_dob_before_issue,
    check_expiry_not_past,
    check_issue_before_expiry,
    check_mandatory_fields,
    check_schema,
    check_temporal_issue_not_future,
)
from src.evidence_validation.cross_document import check_no_duplicate_document_type
from src.service import verify_case

REFERENCE = date(2026, 9, 9)


def _field(value):
    return EvidenceField(
        value=value, normalized_value=value, confidence=0.9 if value is not None else 0.0,
        source="test", provenance="test#field", warnings=[] if value is not None else ["FIELD_NOT_FOUND"],
    )


def _evidence(document_id="D1", dtype=DocumentType.PASSPORT, quality=DocumentQuality.NORMAL, **fields):
    return DocumentEvidence(
        document_id=document_id, document_type=dtype,
        fields={name: _field(value) for name, value in fields.items()},
        quality=quality, extraction_warnings=[], provider="test", evidence_reference="test:source",
    )


_CLEAN = dict(
    full_name="Test Person", date_of_birth="1990-01-01", document_number="PXT100184",
    issue_date="2020-01-01", expiry_date="2030-01-01", nationality="Republic of Meridian",
)


# --- PASS / FAIL / NOT_APPLICABLE / UNKNOWN / NOT_IMPLEMENTED, each exercised ---

def test_pass_state_on_clean_evidence():
    evidence = _evidence(**_CLEAN)
    result = check_expiry_not_past(evidence, REFERENCE)
    assert result.status == ValidationStatus.PASS
    assert result.evidence_references


def test_fail_state_on_bad_document_type():
    evidence = _evidence(dtype=DocumentType.UNKNOWN, **{k: v for k, v in _CLEAN.items() if k != "nationality"})
    result = check_document_type_supported(evidence)
    assert result.status == ValidationStatus.FAIL
    assert result.reason_code == "DOCUMENT_TYPE_UNSUPPORTED"


def test_not_applicable_when_dependency_missing():
    evidence = _evidence(full_name="Test Person")  # no issue_date
    result = check_temporal_issue_not_future(evidence, REFERENCE)
    assert result.status == ValidationStatus.NOT_APPLICABLE


def test_unknown_state_when_evidence_unreadable():
    evidence = _evidence(quality=DocumentQuality.INCOMPLETE_UNREADABLE, full_name="Test Person")
    results = check_mandatory_fields(evidence)
    missing = next(r for r in results if r.reason_code != "MANDATORY_FIELD_PRESENT")
    assert missing.status == ValidationStatus.UNKNOWN
    assert missing.reason_code == "EVIDENCE_UNREADABLE_CANNOT_CONFIRM_FIELD_ABSENCE"


def test_not_implemented_state_for_checksum_capability_boundary():
    evidence = _evidence(**_CLEAN)
    result = check_checksum_signature(evidence)
    assert result.status == ValidationStatus.NOT_IMPLEMENTED
    assert result.severity.value == "INFO"


# --- malformed dates handled safely (requirement 7) -----------------------------

def test_malformed_date_fails_format_check_without_raising():
    evidence = _evidence(full_name="Test Person", expiry_date="not-a-date")
    result = check_date_format(evidence, "expiry_date")
    assert result.status == ValidationStatus.FAIL
    assert result.reason_code == "DATE_FORMAT_INVALID"


def test_malformed_date_never_treated_as_valid_by_dependent_rules():
    # requirement 6: failure to parse must never look like a PASS downstream.
    evidence = _evidence(full_name="Test Person", expiry_date="2026-13-40")
    expiry_result = check_expiry_not_past(evidence, REFERENCE)
    assert expiry_result.status == ValidationStatus.NOT_APPLICABLE
    assert expiry_result.status != ValidationStatus.PASS


def test_empty_string_date_handled_safely():
    evidence = _evidence(full_name="Test Person", issue_date="")
    result = check_date_format(evidence, "issue_date")
    # An explicitly present-but-empty value is a malformed value, not a missing field:
    # it fails safely (no exception) rather than being silently waved through.
    assert result.status == ValidationStatus.FAIL
    assert result.reason_code == "DATE_FORMAT_INVALID"


# --- boundary dates (requirement 11) ---------------------------------------------

def test_expiry_exactly_on_reference_date_passes():
    evidence = _evidence(expiry_date=REFERENCE.isoformat())
    assert check_expiry_not_past(evidence, REFERENCE).status == ValidationStatus.PASS


def test_expiry_one_day_before_reference_date_fails():
    evidence = _evidence(expiry_date="2026-09-08")
    assert check_expiry_not_past(evidence, REFERENCE).status == ValidationStatus.FAIL


def test_expiry_one_day_after_reference_date_passes():
    evidence = _evidence(expiry_date="2026-09-10")
    assert check_expiry_not_past(evidence, REFERENCE).status == ValidationStatus.PASS


def test_issue_date_exactly_on_reference_date_is_not_future():
    evidence = _evidence(issue_date=REFERENCE.isoformat())
    assert check_temporal_issue_not_future(evidence, REFERENCE).status == ValidationStatus.PASS


def test_issue_date_one_day_after_reference_date_fails():
    evidence = _evidence(issue_date="2026-09-10")
    assert check_temporal_issue_not_future(evidence, REFERENCE).status == ValidationStatus.FAIL


def test_issue_date_equal_to_expiry_date_fails_consistency():
    evidence = _evidence(issue_date="2025-01-01", expiry_date="2025-01-01")
    assert check_issue_before_expiry(evidence).status == ValidationStatus.FAIL


def test_issue_date_one_day_before_expiry_date_passes():
    evidence = _evidence(issue_date="2025-01-01", expiry_date="2025-01-02")
    assert check_issue_before_expiry(evidence).status == ValidationStatus.PASS


def test_dob_equal_to_issue_date_fails_cross_field_check():
    evidence = _evidence(date_of_birth="2000-01-01", issue_date="2000-01-01")
    assert check_dob_before_issue(evidence).status == ValidationStatus.FAIL


def test_dob_one_day_before_issue_date_passes():
    evidence = _evidence(date_of_birth="1999-12-31", issue_date="2000-01-01")
    assert check_dob_before_issue(evidence).status == ValidationStatus.PASS


# --- schema validation is independent of the extraction layer's own claims ------

def test_schema_fails_if_field_set_does_not_match_expected_shape():
    evidence = DocumentEvidence(
        document_id="D1", document_type=DocumentType.PASSPORT,
        fields={"full_name": _field("Test Person")},  # missing the rest of the passport schema
        quality=DocumentQuality.NORMAL, extraction_warnings=[], provider="test", evidence_reference="test:source",
    )
    assert check_schema(evidence).status == ValidationStatus.FAIL


def test_schema_not_applicable_for_unknown_type():
    evidence = _evidence(dtype=DocumentType.UNKNOWN, full_name="Test Person")
    assert check_schema(evidence).status == ValidationStatus.NOT_APPLICABLE


# --- extraction failure vs. validation failure are kept distinct (requirement 10) -

def test_missing_field_is_not_applicable_not_a_fabricated_pass_or_fail_in_dependent_rules():
    evidence = _evidence(full_name="Test Person")  # expiry_date never extracted
    date_format = check_date_format(evidence, "expiry_date")
    expiry = check_expiry_not_past(evidence, REFERENCE)
    assert date_format.status == ValidationStatus.NOT_APPLICABLE
    assert date_format.reason_code == "DATE_NOT_EXTRACTED"
    assert expiry.status == ValidationStatus.NOT_APPLICABLE
    assert expiry.reason_code == "EXPIRY_DATE_NOT_EXTRACTED"


# --- cross-document consistency (structural, distinct from identity_resolution) -

def test_duplicate_document_type_in_case_fails():
    docs = [
        _evidence("D1", DocumentType.PASSPORT, **_CLEAN),
        _evidence("D2", DocumentType.PASSPORT, **_CLEAN),
    ]
    result = check_no_duplicate_document_type(docs)
    assert result.status == ValidationStatus.FAIL
    assert result.reason_code == "DUPLICATE_DOCUMENT_TYPES"


def test_distinct_document_types_in_case_pass():
    docs = [
        _evidence("D1", DocumentType.PASSPORT, **_CLEAN),
        _evidence("D2", DocumentType.NATIONAL_ID, **_CLEAN),
    ]
    result = check_no_duplicate_document_type(docs)
    assert result.status == ValidationStatus.PASS


# --- every finding traces back to evidence (requirement 12) ---------------------

def test_every_result_carries_evidence_references():
    evidence = _evidence(**_CLEAN)
    report = validate_document(evidence)
    for result in report.results:
        assert result.evidence_references, f"{result.rule_id} has no evidence_references"


# --- injectable reference date (requirement 5) -----------------------------------

def test_reference_date_is_injectable_without_touching_the_frozen_default():
    evidence = _evidence(expiry_date="2020-01-01")
    default_result = validate_document(evidence)  # uses the frozen repository reference date
    injected_result = validate_document(evidence, reference_date=date(2015, 1, 1))
    expiry_default = next(r for r in default_result.results if r.rule_id == "EXPIRY-NOT-PAST")
    expiry_injected = next(r for r in injected_result.results if r.rule_id == "EXPIRY-NOT-PAST")
    assert expiry_default.status == ValidationStatus.FAIL  # 2020 is before the frozen 2026-09-09 default
    assert expiry_injected.status == ValidationStatus.PASS  # but not before an injected 2015-01-01 clock
    assert default_result.reference_date != injected_result.reference_date


# --- real-dataset integration: config-driven, decisioning untouched -------------

def test_real_case_004_reports_expiry_fail_and_decision_is_unchanged():
    result = verify_case("CASE-004")
    passport_report = next(dr for dr in result.validation.document_reports if dr.document_id == "CASE-004-PASSPORT")
    expiry_result = next(r for r in passport_report.results if r.rule_id == "EXPIRY-NOT-PAST")
    assert expiry_result.status == ValidationStatus.FAIL
    # The legacy decision policy (src/rules.py) is unchanged by this stage.
    assert result.decision == "REJECT"
    assert "DOCUMENT_EXPIRED" in result.reason_codes


def test_clean_case_has_no_failures_and_decision_is_unchanged():
    result = verify_case("CASE-001")
    for dr in result.validation.document_reports:
        assert all(r.status != ValidationStatus.FAIL for r in dr.results)
    assert result.decision == "APPROVE"
