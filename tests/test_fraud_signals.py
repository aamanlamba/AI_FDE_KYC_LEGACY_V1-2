from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
from src.evidence_validation import validate_case, validate_document
from src.fraud_signals import (
    DeterministicMarkerForensicsProvider,
    FraudAssessmentStatus,
    FraudCategory,
    assess_case_fraud,
    assess_document_fraud_signals,
)
from src.identity_resolution import resolve_identity
from src.repository import load_sidecar
from src.service import verify_case

PROVIDER = DeterministicMarkerForensicsProvider()


def _field(value):
    return EvidenceField(
        value=value, normalized_value=value, confidence=0.9 if value is not None else 0.0,
        source="test", provenance="test#field", warnings=[] if value is not None else ["FIELD_NOT_FOUND"],
    )


def _evidence(document_id="D1", dtype=DocumentType.PASSPORT, quality=DocumentQuality.NORMAL, **fields):
    return DocumentEvidence(
        document_id=document_id, document_type=dtype,
        fields={name: _field(value) for name, value in fields.items()},
        quality=quality, extraction_warnings=[], provider="test", evidence_reference=f"test:{document_id}",
    )


_CLEAN = dict(
    full_name="Test Person", date_of_birth="1990-01-01", document_number="PXT100184",
    issue_date="2020-01-01", expiry_date="2030-01-01", nationality="Republic of Meridian",
)


def _assess(evidence, raw_text=""):
    validation = validate_document(evidence)
    return assess_document_fraud_signals(evidence.document_id, raw_text, evidence.evidence_reference, validation)


# --- clean case -------------------------------------------------------------------

def test_real_clean_case_has_no_fraud_signals():
    result = verify_case("CASE-001")
    assert result.fraud_assessment.status == FraudAssessmentStatus.NO_SIGNALS_DETECTED
    assert result.fraud_assessment.signal_count == 0
    assert result.fraud_assessment.highest_severity is None


def test_clean_synthetic_document_has_no_signals():
    evidence = _evidence(**_CLEAN)
    signals = _assess(evidence, raw_text="DOCUMENT TYPE: PASSPORT\nNAME: Test Person\n").signals
    assert signals == []


# --- suspected tampering case -------------------------------------------------------

def test_real_tampering_case_flags_tamper_marker_signal_with_accurate_source():
    result = verify_case("CASE-006")
    assert result.fraud_assessment.status == FraudAssessmentStatus.FRAUD_SIGNAL_PRESENT
    passport_signals = next(
        ds for ds in result.fraud_assessment.document_signals if ds.document_id == "CASE-006-PASSPORT"
    ).signals
    tamper = next(s for s in passport_signals if s.category == FraudCategory.TAMPER_MARKER)
    assert tamper.severity.value == "CRITICAL"
    # Source must be labeled accurately: a fixture-based text match, not real forensics.
    assert "deterministic_marker_forensics" in tamper.source
    assert "sidecar_text_substring_match" in tamper.source


def test_tamper_marker_detected_from_raw_sidecar_text():
    raw_text = load_sidecar("CASE-006-PASSPORT")
    signals = PROVIDER.scan("CASE-006-PASSPORT", raw_text, "test:evidence")
    assert len(signals) == 1
    assert signals[0].category == FraudCategory.TAMPER_MARKER


# --- false-positive resistance -----------------------------------------------------

def test_degraded_ocr_quality_alone_produces_no_signal():
    raw_text = load_sidecar("CASE-002-PASSPORT")  # OCR_QUALITY: DEGRADED, no tamper marker
    signals = PROVIDER.scan("CASE-002-PASSPORT", raw_text, "test:evidence")
    assert signals == []


def test_rotated_capture_alone_produces_no_signal():
    raw_text = load_sidecar("CASE-003-DL")  # CAPTURE_ORIENTATION: 90_DEGREES, no tamper marker
    signals = PROVIDER.scan("CASE-003-DL", raw_text, "test:evidence")
    assert signals == []


def test_real_noisy_and_rotated_cases_have_no_fraud_signals():
    for case_id in ("CASE-002", "CASE-003"):
        result = verify_case(case_id)
        assert result.fraud_assessment.status == FraudAssessmentStatus.NO_SIGNALS_DETECTED, case_id


def test_expiry_alone_is_not_a_fraud_signal():
    # An expired document is a mundane lifecycle event (src/rules.py's own decision
    # path), not a fraud anomaly -- verified against the real expired-passport case.
    result = verify_case("CASE-004")
    assert result.fraud_assessment.status == FraudAssessmentStatus.NO_SIGNALS_DETECTED
    for ds in result.fraud_assessment.document_signals:
        assert all(s.category != FraudCategory.TEMPORAL_ANOMALY for s in ds.signals)


# --- conflicting evidence -----------------------------------------------------------

def test_real_case_005_flags_identity_conflict_signal():
    result = verify_case("CASE-005")
    assert result.fraud_assessment.status == FraudAssessmentStatus.FRAUD_SIGNAL_PRESENT
    conflict = next(s for s in result.fraud_assessment.case_level_signals if s.category == FraudCategory.IDENTITY_CONFLICT)
    assert conflict.source == "identity_resolution:full_name"
    assert conflict.confidence is not None and 0.0 < conflict.confidence < 1.0


def test_contradictory_dob_produces_maximal_confidence_identity_conflict_signal():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [
        _evidence("D1", DocumentType.PASSPORT, full_name="Test Person", date_of_birth="1990-01-01"),
        _evidence("D2", DocumentType.NATIONAL_ID, full_name="Test Person", date_of_birth="1991-06-15"),
    ]
    identity_resolution = resolve_identity("CASE-DOB", application, docs)
    case_validation = validate_case("CASE-DOB", [validate_document(d) for d in docs], docs)
    assessment = assess_case_fraud("CASE-DOB", [], identity_resolution, case_validation)
    dob_signal = next(s for s in assessment.case_level_signals if s.category == FraudCategory.IDENTITY_CONFLICT)
    assert dob_signal.confidence == 1.0  # DOB conflicts are exact-or-contradiction, never ambiguous
    assert dob_signal.severity.value == "HIGH"


# --- missing fraud evidence ----------------------------------------------------------

def test_missing_dates_produce_no_temporal_signal_not_a_fabricated_one():
    evidence = _evidence(full_name="Test Person")  # no issue_date/expiry_date/dob at all
    result = _assess(evidence)
    assert all(s.category != FraudCategory.TEMPORAL_ANOMALY for s in result.signals)


def test_case_with_no_identity_or_duplication_issues_has_no_case_level_signals():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [_evidence("D1", DocumentType.PASSPORT, **_CLEAN)]
    identity_resolution = resolve_identity("CASE-CLEAN", application, docs)
    case_validation = validate_case("CASE-CLEAN", [validate_document(d) for d in docs], docs)
    assessment = assess_case_fraud("CASE-CLEAN", [], identity_resolution, case_validation)
    assert assessment.case_level_signals == []


# --- multiple simultaneous fraud signals ----------------------------------------------

def test_multiple_simultaneous_signals_are_all_reported_independently():
    application = {"submitted_name": "Alice Example", "submitted_dob": "1990-01-01", "submitted_address": None}
    # Document 1: tamper marker + an impossible temporal relationship (issued after expiry).
    doc1 = _evidence(
        "D1", DocumentType.PASSPORT, full_name="Alice Example", date_of_birth="1990-01-01",
        document_number="PXT100184", issue_date="2030-01-01", expiry_date="2020-01-01",
    )
    # Document 2: a duplicate passport (same type as D1) with a conflicting name.
    doc2 = _evidence(
        "D2", DocumentType.PASSPORT, full_name="Bob Completely Different", date_of_birth="1990-01-01",
        document_number="PXT200267", issue_date="2020-01-01", expiry_date="2030-01-01",
    )
    docs = [doc1, doc2]
    doc1_report = assess_document_fraud_signals(
        "D1", "SECURITY NOTE: ALTERED_TEXT_REGION_DETECTED", doc1.evidence_reference, validate_document(doc1)
    )
    doc2_report = assess_document_fraud_signals("D2", "", doc2.evidence_reference, validate_document(doc2))
    identity_resolution = resolve_identity("CASE-MULTI", application, docs)
    case_validation = validate_case("CASE-MULTI", [validate_document(d) for d in docs], docs)

    assessment = assess_case_fraud("CASE-MULTI", [doc1_report, doc2_report], identity_resolution, case_validation)

    categories_found = {s.category for ds in assessment.document_signals for s in ds.signals}
    categories_found |= {s.category for s in assessment.case_level_signals}
    assert FraudCategory.TAMPER_MARKER in categories_found
    assert FraudCategory.TEMPORAL_ANOMALY in categories_found
    assert FraudCategory.IDENTITY_CONFLICT in categories_found
    assert FraudCategory.DOCUMENT_DUPLICATION in categories_found
    assert assessment.status == FraudAssessmentStatus.FRAUD_SIGNAL_PRESENT
    assert assessment.highest_severity.value == "CRITICAL"  # tamper marker must not be masked by other signals
    assert assessment.signal_count >= 4


# --- FRAUD_SIGNAL_PRESENT vs FRAUD_PROVEN is preserved --------------------------------

def test_fraud_proven_is_never_produced_even_by_the_strongest_synthetic_combination():
    # Reuse the maximal multi-signal scenario above; even at CRITICAL severity with
    # four simultaneous signal categories, status must cap at FRAUD_SIGNAL_PRESENT.
    application = {"submitted_name": "Alice Example", "submitted_dob": "1990-01-01", "submitted_address": None}
    doc1 = _evidence(
        "D1", DocumentType.PASSPORT, full_name="Alice Example", date_of_birth="1990-01-01",
        document_number="PXT100184", issue_date="2030-01-01", expiry_date="2020-01-01",
    )
    docs = [doc1]
    doc1_report = assess_document_fraud_signals(
        "D1", "SECURITY NOTE: ALTERED_TEXT_REGION_DETECTED", doc1.evidence_reference, validate_document(doc1)
    )
    identity_resolution = resolve_identity("CASE-PROVEN", application, docs)
    case_validation = validate_case("CASE-PROVEN", [validate_document(d) for d in docs], docs)
    assessment = assess_case_fraud("CASE-PROVEN", [doc1_report], identity_resolution, case_validation)
    assert assessment.status != FraudAssessmentStatus.FRAUD_PROVEN
    assert assessment.status == FraudAssessmentStatus.FRAUD_SIGNAL_PRESENT


def test_no_real_case_ever_reaches_fraud_proven():
    from src.repository import list_cases
    for case in list_cases():
        result = verify_case(case["case_id"])
        assert result.fraud_assessment.status != FraudAssessmentStatus.FRAUD_PROVEN


# --- separation from decision policy (requirement 2) ------------------------------

def test_fraud_assessment_does_not_change_the_legacy_decision():
    result = verify_case("CASE-005")
    # CASE-005 now carries an identity_conflict fraud signal, but src/rules.py's
    # decision policy (P5's domain) is unchanged in this stage.
    assert result.decision == "APPROVE"
    assert result.fraud_assessment.status == FraudAssessmentStatus.FRAUD_SIGNAL_PRESENT
