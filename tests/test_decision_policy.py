from src.decision_policy import (
    POLICY_VERSION,
    DocumentEvidenceSummary,
    assess_case_risk,
    build_evidence_bundle,
)
from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
from src.evidence_validation import validate_case, validate_document
from src.fraud_signals import assess_case_fraud, assess_document_fraud_signals
from src.identity_resolution import resolve_identity
from src.repository import list_cases
from src.service import verify_case


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


def _build_bundle(case_id, application, documents_evidence, raw_texts=None):
    raw_texts = raw_texts or {d.document_id: "" for d in documents_evidence}
    validations = [validate_document(d) for d in documents_evidence]
    fraud_per_doc = [
        assess_document_fraud_signals(d.document_id, raw_texts[d.document_id], d.evidence_reference, v)
        for d, v in zip(documents_evidence, validations)
    ]
    identity_resolution = resolve_identity(case_id, application, documents_evidence)
    case_validation = validate_case(case_id, validations, documents_evidence)
    fraud_assessment = assess_case_fraud(case_id, fraud_per_doc, identity_resolution, case_validation)
    summaries = [
        DocumentEvidenceSummary(
            document_id=d.document_id, legacy_decision="APPROVE", legacy_reason_codes=["BASELINE_RULES_PASSED"],
            evidence=d, validation=v, fraud_signals=fs,
        )
        for d, v, fs in zip(documents_evidence, validations, fraud_per_doc)
    ]
    return build_evidence_bundle(case_id, summaries, identity_resolution, case_validation, fraud_assessment)


# --- clean approval -----------------------------------------------------------------

def test_clean_case_approves_with_zero_risk_factors():
    result = verify_case("CASE-001")
    assert result.decision == "APPROVE"
    assert result.risk_assessment.policy_outcome == "APPROVE"
    assert result.risk_assessment.risk_factors == []
    assert result.risk_assessment.hard_stop_triggered is False
    assert result.risk_assessment.reason_codes == ["POLICY_APPROVED_NO_RISK_FACTORS"]


# --- expired document -----------------------------------------------------------------

def test_expired_document_rejects_via_hard_stop_and_preserves_legacy_reason_code():
    result = verify_case("CASE-004")
    assert result.decision == "REJECT"
    assert result.risk_assessment.hard_stop_triggered is True
    hard_stops = [f for f in result.risk_assessment.risk_factors if f.triggers_hard_stop]
    assert any(f.category.value == "document_decision" for f in hard_stops)
    # requirement 9: legacy reason code compatibility preserved alongside new codes
    assert "DOCUMENT_EXPIRED" in result.reason_codes
    assert any(code.startswith("HARD_STOP:") for code in result.reason_codes)


# --- suspected tampering ---------------------------------------------------------------

def test_suspected_tampering_rejects_via_hard_stop_with_critical_fraud_signal():
    result = verify_case("CASE-006")
    assert result.decision == "REJECT"
    assert result.risk_assessment.hard_stop_triggered is True
    assert "SUSPECTED_TAMPERING" in result.reason_codes
    fraud_factor = next(f for f in result.risk_assessment.risk_factors if f.category.value == "fraud_signal")
    assert fraud_factor.severity.value == "CRITICAL"
    assert fraud_factor.triggers_hard_stop is True


# --- identity mismatch: the flagship fix ------------------------------------------------

def test_identity_mismatch_case_005_now_reviews_instead_of_silently_approving():
    result = verify_case("CASE-005")
    # This is the headline behavioural change of this stage: P0-P4 all left CASE-005 at
    # APPROVE despite an unreconciled name discrepancy. It must no longer be APPROVE.
    assert result.decision == "REVIEW"
    assert result.risk_assessment.policy_outcome == "REVIEW"
    assert result.risk_assessment.hard_stop_triggered is False  # non-DOB conflict is review-level, not a hard stop
    assert result.risk_assessment.identity_conflict_count >= 1
    identity_factor = next(f for f in result.risk_assessment.risk_factors if f.category.value == "identity_conflict")
    assert identity_factor.severity.value == "HIGH"
    assert any(code.startswith("REVIEW:") for code in result.reason_codes)


def test_dob_conflict_is_a_hard_stop_unlike_name_conflict():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [
        _evidence("D1", DocumentType.PASSPORT, full_name="Test Person", date_of_birth="1990-01-01"),
        _evidence("D2", DocumentType.NATIONAL_ID, full_name="Test Person", date_of_birth="1991-06-15"),
    ]
    bundle = _build_bundle("CASE-DOB", application, docs)
    assessment = assess_case_risk(bundle)
    assert assessment.policy_outcome == "REJECT"
    assert assessment.hard_stop_triggered is True
    dob_factor = next(f for f in assessment.risk_factors if f.factor_id.endswith("date_of_birth:CONFLICT"))
    assert dob_factor.triggers_hard_stop is True
    assert dob_factor.severity.value == "CRITICAL"


# --- low-quality document ---------------------------------------------------------------

def test_low_quality_unreadable_document_triggers_review_not_approve():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [_evidence("D1", DocumentType.PASSPORT, quality=DocumentQuality.INCOMPLETE_UNREADABLE, full_name="Test Person")]
    bundle = _build_bundle("CASE-LOWQ", application, docs)
    assessment = assess_case_risk(bundle)
    assert assessment.policy_outcome == "REVIEW"
    assert assessment.hard_stop_triggered is False
    assert any(f.category.value == "evidence_quality" for f in assessment.risk_factors)


# --- insufficient evidence ---------------------------------------------------------------

def test_insufficient_identity_evidence_triggers_review():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    # A passport-only case: no document in this synthetic set carries an address field,
    # so the address attribute has only one source (the application) -> INSUFFICIENT_EVIDENCE.
    docs = [_evidence("D1", DocumentType.PASSPORT, **_CLEAN)]
    bundle = _build_bundle("CASE-INSUFF", application, docs)
    assessment = assess_case_risk(bundle)
    assert assessment.policy_outcome == "REVIEW"
    assert any(f.category.value == "identity_uncertainty" for f in assessment.risk_factors)


# --- multiple competing signals -----------------------------------------------------------

def test_multiple_competing_signals_hard_stop_wins_and_all_factors_remain_visible():
    application = {"submitted_name": "Alice Example", "submitted_dob": "1990-01-01", "submitted_address": None}
    doc1 = _evidence(
        "D1", DocumentType.PASSPORT, full_name="Alice Example", date_of_birth="1990-01-01",
        document_number="PXT100184", issue_date="2030-01-01", expiry_date="2020-01-01",  # impossible temporal relationship
    )
    doc2 = _evidence(
        "D2", DocumentType.PASSPORT, full_name="Bob Completely Different", date_of_birth="1990-01-01",
        document_number="PXT200267", issue_date="2020-01-01", expiry_date="2030-01-01",
    )
    docs = [doc1, doc2]
    raw_texts = {"D1": "SECURITY NOTE: ALTERED_TEXT_REGION_DETECTED", "D2": ""}
    bundle = _build_bundle("CASE-MULTI", application, docs, raw_texts)
    assessment = assess_case_risk(bundle)

    assert assessment.policy_outcome == "REJECT"
    assert assessment.hard_stop_triggered is True
    categories = {f.category.value for f in assessment.risk_factors}
    # A hard-stop (tamper marker) coexists with softer signals (identity conflict,
    # document duplication) -- REJECT must not hide the other findings from the analyst.
    assert "fraud_signal" in categories
    assert "identity_conflict" in categories
    assert "validation_failure" in categories
    assert len(assessment.risk_factors) >= 4
    review_only_codes = [c for c in assessment.reason_codes if c.startswith("REVIEW:")]
    assert review_only_codes, "non-hard-stop factors must still surface their own reason codes"


# --- threshold boundaries -----------------------------------------------------------------

def test_zero_factors_is_the_only_path_to_approve():
    # A fully corroborated case: address has two agreeing sources (application +
    # national ID), avoiding a spurious INSUFFICIENT_EVIDENCE factor from an
    # unsupplied attribute -- this is exercised deliberately by the insufficient-
    # evidence test above.
    application = {
        "submitted_name": "Test Person", "submitted_dob": "1990-01-01",
        "submitted_address": "1 Example Street, Meridian City",
    }
    docs = [_evidence(
        "D1", DocumentType.NATIONAL_ID, full_name="Test Person", date_of_birth="1990-01-01",
        document_number="MID-1234-5678", issue_date="2020-01-01", expiry_date="2030-01-01",
        address="1 Example Street, Meridian City",
    )]
    bundle = _build_bundle("CASE-ZERO", application, docs)
    assessment = assess_case_risk(bundle)
    assert assessment.risk_factors == []
    assert assessment.policy_outcome == "APPROVE"


def test_exactly_one_minor_factor_is_not_silently_absorbed_into_approve():
    # A single fuzzy-name identity signal, nothing else -- still must not be APPROVE.
    application = {"submitted_name": "Jonathan Smyth", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [_evidence("D1", DocumentType.PASSPORT, full_name="Jon A. Smith", date_of_birth="1990-01-01",
                       document_number="PXT100184", issue_date="2020-01-01", expiry_date="2030-01-01")]
    bundle = _build_bundle("CASE-ONE", application, docs)
    assessment = assess_case_risk(bundle)
    assert len(assessment.risk_factors) >= 1
    assert assessment.policy_outcome != "APPROVE"


def test_uncertainty_saturates_at_one_and_never_exceeds_range():
    application = {"submitted_name": None, "submitted_dob": None, "submitted_address": None}
    docs = [
        _evidence("D1", DocumentType.PASSPORT, quality=DocumentQuality.INCOMPLETE_UNREADABLE),
        _evidence("D2", DocumentType.NATIONAL_ID, quality=DocumentQuality.INCOMPLETE_UNREADABLE),
    ]
    bundle = _build_bundle("CASE-UNCERTAIN", application, docs)
    assessment = assess_case_risk(bundle)
    assert 0.0 <= assessment.uncertainty <= 1.0
    assert 0.0 <= assessment.evidence_strength <= 1.0


# --- policy metadata, reproducibility, explanation ------------------------------------

def test_policy_version_is_present_and_stable():
    result = verify_case("CASE-001")
    assert result.risk_assessment.policy_version == POLICY_VERSION
    assert POLICY_VERSION  # non-empty


def test_decision_is_reproducible_from_the_same_evidence_and_policy_version():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [_evidence("D1", DocumentType.PASSPORT, **_CLEAN)]
    bundle = _build_bundle("CASE-REPRO", application, docs)
    first = assess_case_risk(bundle)
    second = assess_case_risk(bundle)
    assert first.model_dump() == second.model_dump()


def test_explanation_is_analyst_readable_and_case_specific():
    result = verify_case("CASE-006")
    explanation = result.risk_assessment.explanation
    assert "CASE-006" in explanation
    assert "REJECT" in explanation
    assert len(explanation) > 20


def test_extraction_confidence_and_identity_risk_are_not_conflated():
    # A case with perfect extraction confidence but a genuine identity conflict must
    # still show the conflict via risk_factors/identity_conflict_count, not have it
    # washed out by a single blended "risk score".
    result = verify_case("CASE-005")
    ra = result.risk_assessment
    assert ra.identity_conflict_count >= 1
    # evidence_strength blends two named components; it must not itself BE the policy
    # outcome or hide the conflict -- the conflict is independently visible.
    assert any(f.category.value == "identity_conflict" for f in ra.risk_factors)


def test_all_real_cases_are_reproducible_across_repeated_calls():
    # As of P9, decision_lineage.trace_id is intentionally unique per call (it
    # identifies a specific traced operation, not a property of the evidence) --
    # bind the same trace context for both calls so this test still verifies what it
    # means to: identical evidence + identical policy version produces an identical
    # decision, not that two separate operations share a trace id.
    from src.observability import bind_trace_context

    for case in list_cases():
        with bind_trace_context(trace_id="repro-test-trace"):
            first = verify_case(case["case_id"])
            second = verify_case(case["case_id"])
        assert first.model_dump() == second.model_dump()
