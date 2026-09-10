"""Metamorphic tests: compare a baseline case against a transformed variant and assert
a relationship holds -- either invariance (harmless formatting changes must not move
the decision, P7 requirement 7) or sensitivity (a genuine change must move it, P7
requirement 8, guarding against a harness that would trivially pass if the system
just ignored its input).

All cases here are synthetic, built directly via eval.pipeline -- this is about
end-to-end case-decision behaviour, complementing (not duplicating) the unit-level
normalization tests in tests/test_identity_resolution.py.
"""

from dataclasses import dataclass
from typing import Literal

from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField

from .pipeline import run_synthetic_case


@dataclass
class MetamorphicResult:
    name: str
    kind: Literal["invariance", "adversarial_sensitivity"]
    passed: bool
    baseline_decision: str
    transformed_decision: str
    detail: str


def _field(value: str | None) -> EvidenceField:
    return EvidenceField(
        value=value, normalized_value=value, confidence=0.9 if value is not None else 0.0,
        source="eval", provenance="eval#field", warnings=[] if value is not None else ["FIELD_NOT_FOUND"],
    )


def _passport(document_id: str, **fields) -> DocumentEvidence:
    return DocumentEvidence(
        document_id=document_id, document_type=DocumentType.PASSPORT,
        fields={name: _field(value) for name, value in fields.items()},
        quality=DocumentQuality.NORMAL, extraction_warnings=[], provider="eval", evidence_reference=f"eval:{document_id}",
    )


def _national_id(document_id: str, **fields) -> DocumentEvidence:
    return DocumentEvidence(
        document_id=document_id, document_type=DocumentType.NATIONAL_ID,
        fields={name: _field(value) for name, value in fields.items()},
        quality=DocumentQuality.NORMAL, extraction_warnings=[], provider="eval", evidence_reference=f"eval:{document_id}",
    )


def _baseline() -> tuple[dict, list[DocumentEvidence]]:
    application = {"submitted_name": "Kavya Reddy", "submitted_dob": "1993-08-11", "submitted_address": "9 Lotus Lane, Meridian City"}
    passport = _passport(
        "MM-BASELINE-PASSPORT", full_name="Kavya Reddy", date_of_birth="1993-08-11",
        document_number="PXT700331", issue_date="2020-01-01", expiry_date="2030-01-01",
        nationality="Republic of Meridian",
    )
    nid = _national_id(
        "MM-BASELINE-NID", full_name="Kavya Reddy", date_of_birth="1993-08-11",
        document_number="MID-4455-6677", issue_date="2020-01-01", expiry_date="2030-01-01",
        address="9 Lotus Lane, Meridian City",
    )
    return application, [passport, nid]


def _run(case_id: str, application: dict, documents: list[DocumentEvidence], raw_texts: dict | None = None) -> str:
    result = run_synthetic_case(case_id, application, documents, raw_texts or {})
    return result.decision


def _invariance_check(name: str, transform) -> MetamorphicResult:
    application, documents = _baseline()
    baseline_decision = _run("MM-BASELINE", application, documents)
    t_application, t_documents = transform(dict(application), list(documents))
    transformed_decision = _run(f"MM-{name}", t_application, t_documents)
    passed = baseline_decision == transformed_decision
    return MetamorphicResult(
        name=name, kind="invariance", passed=passed,
        baseline_decision=baseline_decision, transformed_decision=transformed_decision,
        detail=f"expected invariant decision; baseline={baseline_decision} transformed={transformed_decision}",
    )


def _sensitivity_check(name: str, transform, raw_texts: dict | None = None) -> MetamorphicResult:
    application, documents = _baseline()
    baseline_decision = _run("MM-BASELINE", application, documents)
    t_application, t_documents, t_raw_texts = transform(dict(application), list(documents))
    transformed_decision = _run(f"MM-{name}", t_application, t_documents, t_raw_texts)
    passed = baseline_decision != transformed_decision
    return MetamorphicResult(
        name=name, kind="adversarial_sensitivity", passed=passed,
        baseline_decision=baseline_decision, transformed_decision=transformed_decision,
        detail=f"expected the decision to change; baseline={baseline_decision} transformed={transformed_decision}",
    )


def _copy_with_field(evidence: DocumentEvidence, field_name: str, new_value: str) -> DocumentEvidence:
    fields = dict(evidence.fields)
    fields[field_name] = _field(new_value)
    return evidence.model_copy(update={"fields": fields})


# --- invariance transforms (harmless: decision must not change) ---------------------

def _transform_case(application: dict, documents: list[DocumentEvidence]):
    application["submitted_name"] = application["submitted_name"].upper()
    documents = [_copy_with_field(d, "full_name", d.fields["full_name"].value.upper()) for d in documents]
    return application, documents


def _transform_spacing(application: dict, documents: list[DocumentEvidence]):
    application["submitted_name"] = "  " + "  ".join(application["submitted_name"].split()) + "  "
    return application, documents


def _transform_punctuation(application: dict, documents: list[DocumentEvidence]):
    documents = [
        _copy_with_field(d, "full_name", d.fields["full_name"].value.replace(" ", ". ") + ".")
        for d in documents
    ]
    return application, documents


def _transform_document_ordering(application: dict, documents: list[DocumentEvidence]):
    return application, list(reversed(documents))


# --- adversarial transforms (genuine: decision must change) -------------------------

def _transform_dob_corruption(application: dict, documents: list[DocumentEvidence]):
    documents = list(documents)
    documents[1] = _copy_with_field(documents[1], "date_of_birth", "1975-01-01")  # genuinely different DOB
    return application, documents, {}


def _transform_tamper_marker(application: dict, documents: list[DocumentEvidence]):
    raw_texts = {documents[0].document_id: "SECURITY NOTE: ALTERED_TEXT_REGION_DETECTED"}
    return application, documents, raw_texts


def _transform_different_person(application: dict, documents: list[DocumentEvidence]):
    documents = list(documents)
    documents[1] = _copy_with_field(documents[1], "full_name", "Completely Different Person")
    return application, documents, {}


def run_metamorphic_suite() -> list[MetamorphicResult]:
    return [
        _invariance_check("case_invariance", _transform_case),
        _invariance_check("spacing_invariance", _transform_spacing),
        _invariance_check("punctuation_invariance", _transform_punctuation),
        _invariance_check("document_ordering_invariance", _transform_document_ordering),
        _sensitivity_check("dob_corruption_sensitivity", _transform_dob_corruption),
        _sensitivity_check("tamper_marker_sensitivity", _transform_tamper_marker),
        _sensitivity_check("different_person_sensitivity", _transform_different_person),
    ]
