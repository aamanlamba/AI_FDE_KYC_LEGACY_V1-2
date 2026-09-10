import pytest
from pydantic import ValidationError

from src.document_intelligence import (
    DeterministicSidecarProvider,
    DocumentEvidence,
    DocumentIntelligenceProvider,
    DocumentQuality,
    DocumentType,
    ProviderContractError,
    extract_evidence,
    get_default_provider,
)
from src.document_intelligence.sidecar_provider import build_document_evidence
from src.repository import list_cases, load_ground_truth
from src.service import verify_document

PROVIDER = DeterministicSidecarProvider()

GROUND_TRUTH_COMPARABLE_FIELDS = (
    "full_name",
    "date_of_birth",
    "document_number",
    "issue_date",
    "expiry_date",
    "address",
    "nationality",
)


# --- clean extraction -------------------------------------------------------

def test_clean_extraction_matches_ground_truth_and_is_high_confidence():
    for document_id in ("CASE-001-PASSPORT", "CASE-001-NID", "CASE-001-DL"):
        evidence = PROVIDER.extract(document_id)
        gt = load_ground_truth(document_id)
        assert evidence.quality == DocumentQuality.NORMAL
        assert evidence.document_type.value == gt["document_type"]
        for field_name in GROUND_TRUTH_COMPARABLE_FIELDS:
            gt_value = gt.get(field_name)
            if gt_value is None:
                continue
            field = evidence.fields[field_name]
            assert field.value == gt_value
            assert field.normalized_value == gt_value
            assert field.confidence >= 0.9
            assert field.warnings == []


# --- rotated document --------------------------------------------------------

def test_rotated_document_flagged_with_reduced_confidence():
    evidence = PROVIDER.extract("CASE-003-DL")
    assert evidence.quality == DocumentQuality.ROTATED
    assert "CAPTURE_ORIENTATION_ROTATED" in evidence.extraction_warnings
    # Fields are still extracted (deterministic sidecar doesn't lose data on rotation)
    # but confidence must be lower than a normal-quality extraction.
    assert evidence.fields["full_name"].value == "Vikram Sen"
    assert 0.0 < evidence.fields["full_name"].confidence < 0.97


# --- degraded scan -----------------------------------------------------------

def test_degraded_scan_flagged_with_reduced_confidence():
    evidence = PROVIDER.extract("CASE-002-PASSPORT")
    assert evidence.quality == DocumentQuality.DEGRADED
    assert "OCR_QUALITY_DEGRADED" in evidence.extraction_warnings
    assert 0.0 < evidence.fields["full_name"].confidence < 0.97


# --- OCR corruption is preserved, never silently corrected -------------------

def test_ocr_corruption_is_preserved_not_hallucinated():
    evidence = PROVIDER.extract("CASE-005-NID")
    gt = load_ground_truth("CASE-005-NID")
    name_field = evidence.fields["full_name"]
    assert name_field.value == "Moharnmad Rehrnan"
    # Normalization must not "fix" the corruption -- only whitespace-collapse it.
    assert name_field.normalized_value == "Moharnmad Rehrnan"
    assert name_field.value != gt["full_name"]


# --- missing fields ------------------------------------------------------------

def test_missing_fields_are_represented_as_unknown_not_fabricated():
    synthetic_text = (
        "DOCUMENT TYPE: PASSPORT\n"
        "NAME: Test Person\n"
        "DOB: 1990-01-01\n"
        # DOCUMENT NO and EXPIRY DATE deliberately omitted
        "ISSUE DATE: 2020-01-01\n"
        "NATIONALITY: Republic of Meridian\n"
    )
    evidence = build_document_evidence(
        document_id="SYNTHETIC-MISSING-FIELDS",
        raw_text=synthetic_text,
        provider_name="deterministic_sidecar_ocr",
        evidence_reference="synthetic:in-memory",
    )
    for missing in ("document_number", "expiry_date"):
        field = evidence.fields[missing]
        assert field.value is None
        assert field.normalized_value is None
        assert field.confidence == 0.0
        assert "FIELD_NOT_FOUND" in field.warnings
    # present fields are unaffected
    assert evidence.fields["full_name"].value == "Test Person"


# --- unsupported document type --------------------------------------------------

def test_unsupported_document_type_is_classified_as_unknown():
    synthetic_text = (
        "DOCUMENT TYPE: FOREIGN_MILITARY_ID\n"
        "NAME: Test Person\n"
        "DOB: 1990-01-01\n"
        "DOCUMENT NO: XX-000000\n"
        "EXPIRY DATE: 2030-01-01\n"
    )
    evidence = build_document_evidence(
        document_id="SYNTHETIC-UNSUPPORTED-TYPE",
        raw_text=synthetic_text,
        provider_name="deterministic_sidecar_ocr",
        evidence_reference="synthetic:in-memory",
    )
    assert evidence.document_type == DocumentType.UNKNOWN
    assert "UNSUPPORTED_DOCUMENT_TYPE" in evidence.extraction_warnings
    # Unknown-type documents only report fields actually found, no presumed schema.
    assert set(evidence.fields) == {"full_name", "date_of_birth", "document_number", "expiry_date"}


def test_unreadable_evidence_is_flagged_incomplete_unreadable():
    evidence = build_document_evidence(
        document_id="SYNTHETIC-EMPTY",
        raw_text="   \n  ",
        provider_name="deterministic_sidecar_ocr",
        evidence_reference="synthetic:in-memory",
    )
    assert evidence.quality == DocumentQuality.INCOMPLETE_UNREADABLE
    assert "EVIDENCE_UNREADABLE" in evidence.extraction_warnings


# --- malformed provider result --------------------------------------------------

class _BrokenProvider(DocumentIntelligenceProvider):
    name = "broken_provider"

    def extract(self, document_id: str):  # intentionally violates the return contract
        return {"document_id": document_id, "not": "a DocumentEvidence"}


def test_provider_returning_wrong_type_is_rejected():
    with pytest.raises(ProviderContractError):
        extract_evidence(_BrokenProvider(), "CASE-001-PASSPORT")


def test_evidence_construction_enforces_schema_validation():
    with pytest.raises(ValidationError):
        DocumentEvidence(
            document_id="X",
            document_type="not-a-real-document-type",
            fields={},
            quality="not-a-real-quality",
            extraction_warnings=[],
            provider="p",
            evidence_reference="r",
        )


# --- pluggability: a custom provider can stand in without touching service.py --

class _StaticFakeProvider(DocumentIntelligenceProvider):
    name = "static_fake_provider"

    def extract(self, document_id: str) -> DocumentEvidence:
        return DocumentEvidence(
            document_id=document_id,
            document_type=DocumentType.PASSPORT,
            fields={},
            quality=DocumentQuality.NORMAL,
            extraction_warnings=[],
            provider=self.name,
            evidence_reference="fake:source",
        )


def test_custom_provider_satisfies_the_same_contract():
    evidence = extract_evidence(_StaticFakeProvider(), "ANY-ID")
    assert isinstance(evidence, DocumentEvidence)
    assert evidence.provider == "static_fake_provider"


# --- ground-truth comparison across the full synthetic dataset -----------------

def test_full_dataset_extraction_against_ground_truth():
    expected_quality = {
        "CASE-002-PASSPORT": DocumentQuality.DEGRADED,
        "CASE-002-NID": DocumentQuality.DEGRADED,
        "CASE-003-DL": DocumentQuality.ROTATED,
    }
    known_mismatches = {("CASE-005-NID", "full_name")}

    for case in list_cases():
        for document_id in case["document_ids"]:
            evidence = get_default_provider().extract(document_id)
            gt = load_ground_truth(document_id)
            assert evidence.quality == expected_quality.get(document_id, DocumentQuality.NORMAL)
            for field_name in GROUND_TRUTH_COMPARABLE_FIELDS:
                gt_value = gt.get(field_name)
                if gt_value is None:
                    continue
                field = evidence.fields.get(field_name)
                assert field is not None, f"{document_id}: expected field {field_name} to be reported"
                if (document_id, field_name) in known_mismatches:
                    assert field.value != gt_value
                else:
                    assert field.value == gt_value


# --- backward-compatible, additive API response -------------------------------

def test_verify_document_response_is_backward_compatible_and_additive():
    result = verify_document("CASE-001-PASSPORT")
    # legacy contract untouched
    assert result.decision == "APPROVE"
    assert result.parsed_fields["full_name"] == "Aarav Mehta"
    assert result.completeness == 1.0
    # new, additive structured evidence
    assert isinstance(result.evidence, DocumentEvidence)
    assert result.evidence.document_id == "CASE-001-PASSPORT"
    assert result.evidence.provider == "deterministic_sidecar_ocr"
