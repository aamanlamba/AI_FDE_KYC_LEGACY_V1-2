from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
from src.identity_resolution import MatchStatus, compare_names, resolve_identity
from src.service import verify_case


def _field(value: str | None, normalized: str | None = None) -> EvidenceField:
    return EvidenceField(
        value=value,
        normalized_value=normalized if normalized is not None else value,
        confidence=0.9 if value is not None else 0.0,
        source="test",
        provenance="test",
        warnings=[] if value is not None else ["FIELD_NOT_FOUND"],
    )


def _evidence(document_id: str, dtype: DocumentType, **fields: str | None) -> DocumentEvidence:
    return DocumentEvidence(
        document_id=document_id,
        document_type=dtype,
        fields={name: _field(value) for name, value in fields.items()},
        quality=DocumentQuality.NORMAL,
        extraction_warnings=[],
        provider="test",
        evidence_reference="test",
    )


# --- exact match --------------------------------------------------------------

def test_exact_match_across_all_attributes():
    application = {"submitted_name": "Aarav Mehta", "submitted_dob": "1991-04-12", "submitted_address": "18 Cedar Avenue, Meridian City"}
    docs = [
        _evidence("D1", DocumentType.NATIONAL_ID, full_name="Aarav Mehta", date_of_birth="1991-04-12", address="18 Cedar Avenue, Meridian City"),
    ]
    result = resolve_identity("CASE-X", application, docs)
    assert result.overall_status == MatchStatus.EXACT
    assert result.confidence == 1.0
    for ac in result.attribute_comparisons:
        assert ac.status == MatchStatus.EXACT


def test_real_case_001_clean_scenario_is_exact():
    result = verify_case("CASE-001").identity_resolution
    assert result.overall_status == MatchStatus.EXACT
    assert result.confidence == 1.0


# --- harmless name variation ----------------------------------------------------

def test_initial_name_variation_is_normalized_match_not_fuzzy():
    status, similarity, notes = compare_names("John A Smith", "John Andrew Smith")
    assert status == MatchStatus.NORMALIZED_MATCH
    assert "INITIAL_COMPATIBLE" in notes


def test_reordered_name_is_normalized_match():
    status, similarity, notes = compare_names("Smith John", "John Smith")
    assert status == MatchStatus.NORMALIZED_MATCH
    assert "TOKEN_ORDER_DIFFERENT" in notes


def test_punctuation_and_spacing_variation_is_normalized_match():
    status, _, notes = compare_names("O'Neil  Jane", "ONEIL JANE")
    assert status == MatchStatus.NORMALIZED_MATCH


# --- OCR-corrupted surname (real dataset, and the flagship discrepancy) --------

def test_case_005_flags_full_name_conflict_but_dob_and_address_stay_consistent():
    result = verify_case("CASE-005").identity_resolution
    name_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "full_name")
    dob_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "date_of_birth")
    address_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "address")

    # The direct passport-vs-NID comparison is a genuine contradiction (below threshold),
    # even though each individually looks like a plausible variant of the submitted name.
    assert name_attr.status == MatchStatus.CONFLICT
    assert dob_attr.status == MatchStatus.EXACT
    assert address_attr.status == MatchStatus.EXACT

    # A single contradiction is not averaged away by the other clean attributes.
    assert result.overall_status == MatchStatus.CONFLICT
    assert result.confidence == 0.0
    assert any("full_name" in c for c in result.conflicts)


def test_ocr_corrupted_surname_alone_is_fuzzy_not_exact_or_conflict():
    # Isolated pairing: submitted value vs. the OCR-corrupted NID value only.
    status, similarity, _ = compare_names("Mohammad Rehman", "Moharnmad Rehrnan")
    assert status == MatchStatus.FUZZY_MATCH
    assert similarity is not None and similarity < 1.0


# --- matching DOB with name discrepancy (a different, smaller-scale case) ------

def test_matching_dob_does_not_upgrade_a_name_conflict_to_a_match():
    application = {"submitted_name": "Isha Verma", "submitted_dob": "1986-09-19", "submitted_address": None}
    docs = [
        _evidence("D1", DocumentType.PASSPORT, full_name="Nisha Rao", date_of_birth="1986-09-19"),
    ]
    result = resolve_identity("CASE-Y", application, docs)
    name_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "full_name")
    assert name_attr.status == MatchStatus.CONFLICT
    # A matching DOB must not compensate for a name conflict in the overall status.
    assert result.overall_status == MatchStatus.CONFLICT


# --- contradictory DOB (synthetic; not present in the shipped dataset) ---------

def test_contradictory_dob_is_detected_as_conflict_not_averaged():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [
        _evidence("D1", DocumentType.PASSPORT, full_name="Test Person", date_of_birth="1990-01-01"),
        _evidence("D2", DocumentType.NATIONAL_ID, full_name="Test Person", date_of_birth="1991-06-15"),
    ]
    result = resolve_identity("CASE-Z", application, docs)
    dob_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "date_of_birth")
    assert dob_attr.status == MatchStatus.CONFLICT
    # full_name is exact across all three sources, but must not dilute the DOB conflict.
    assert result.overall_status == MatchStatus.CONFLICT
    assert result.confidence == 0.0
    assert any("date_of_birth" in c for c in result.conflicts)


# --- insufficient identity evidence ---------------------------------------------

def test_single_source_attribute_is_insufficient_evidence():
    application = {"submitted_name": "Test Person", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [
        # A passport-only case: no document in this synthetic set carries an address field.
        _evidence("D1", DocumentType.PASSPORT, full_name="Test Person", date_of_birth="1990-01-01"),
    ]
    result = resolve_identity("CASE-W", application, docs)
    address_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "address")
    assert address_attr.status == MatchStatus.INSUFFICIENT_EVIDENCE
    assert address_attr.pairwise == []


def test_no_evidence_at_all_is_insufficient_evidence():
    application = {"submitted_name": None, "submitted_dob": None, "submitted_address": None}
    result = resolve_identity("CASE-V", application, [])
    assert result.overall_status == MatchStatus.INSUFFICIENT_EVIDENCE
    for ac in result.attribute_comparisons:
        assert ac.status == MatchStatus.INSUFFICIENT_EVIDENCE


# --- raw evidence is retained alongside normalized values -----------------------

def test_raw_and_normalized_values_are_both_retained():
    application = {"submitted_name": "john a. smith", "submitted_dob": "1990-01-01", "submitted_address": None}
    docs = [_evidence("D1", DocumentType.PASSPORT, full_name="JOHN A SMITH", date_of_birth="1990-01-01")]
    result = resolve_identity("CASE-U", application, docs)
    name_attr = next(ac for ac in result.attribute_comparisons if ac.attribute == "full_name")
    application_source = next(s for s in name_attr.sources if s.source_id == "SUBMITTED_APPLICATION")
    assert application_source.raw_value == "john a. smith"
    assert application_source.normalized_value == "JOHN A SMITH"


# --- case-level integration: legacy decisioning untouched -----------------------

def test_identity_conflict_now_informs_the_case_decision():
    result = verify_case("CASE-005")
    # At P2, identity_resolution was reporting-only and did not affect `decision`
    # (worst-of-documents, unchanged through P4). As of P5's decision policy, this
    # CONFLICT is a risk factor that correctly escalates the case to REVIEW.
    assert result.identity_resolution.overall_status == MatchStatus.CONFLICT
    assert result.decision == "REVIEW"
