"""Evaluation case catalogue.

Every required category (P7 requirement 3) is represented by at least one case.
Where the real synthetic dataset (data/) already exercises a category faithfully, the
eval case wraps that repository case_id (full-fidelity: goes through src.service, the
real ocr/parser/rules layers included). Categories the 6-case/13-document dataset
cannot naturally exercise (missing evidence, contradictory evidence, adversarial/
malformed input) are built as small, explicitly-synthetic in-memory cases via
eval.pipeline -- never added to data/, so P0-P6's dataset-integrity invariants
(scripts/sanity_check.py's exact case/document counts) are untouched.

Sample sizes are intentionally small and stated explicitly wherever metrics are
reported (P7 requirement 6) -- this catalogue is a curated, adversarial-weighted
regression set, not a representative population sample.
"""

from dataclasses import dataclass, field
from typing import Callable, Literal

from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
from src.policy import Decision

Category = Literal[
    "golden", "noisy", "rotated", "ocr_corrupted", "expired", "identity_variation",
    "fraud_tampering", "missing_evidence", "contradictory_evidence", "adversarial_malformed",
]


@dataclass
class EvalCase:
    case_id: str
    category: Category
    description: str
    source: Literal["repository", "synthetic"]
    repo_case_id: str | None = None
    # For synthetic cases: a zero-argument callable returning
    # (application, documents, raw_texts, legacy_decisions) ready for eval.pipeline.run_synthetic_case.
    build_synthetic: Callable[[], tuple] | None = None
    expected_decision: Decision | None = None
    expected_identity_status: str | None = None  # one of identity_resolution.MatchStatus values
    should_have_identity_conflict: bool | None = None
    expect_exception: type[BaseException] | None = None
    # Real dataset only: document_ids to compare against data/ground_truth for DI metrics.
    ground_truth_document_ids: list[str] = field(default_factory=list)


def _field(value: str | None) -> EvidenceField:
    return EvidenceField(
        value=value, normalized_value=value, confidence=0.9 if value is not None else 0.0,
        source="eval", provenance="eval#field", warnings=[] if value is not None else ["FIELD_NOT_FOUND"],
    )


def _evidence(document_id: str, dtype: DocumentType, quality: DocumentQuality = DocumentQuality.NORMAL, **fields) -> DocumentEvidence:
    return DocumentEvidence(
        document_id=document_id, document_type=dtype,
        fields={name: _field(value) for name, value in fields.items()},
        quality=quality, extraction_warnings=[], provider="eval", evidence_reference=f"eval:{document_id}",
    )


_CLEAN_PASSPORT = dict(
    full_name="Priya Nair", date_of_birth="1988-05-20", document_number="PXT900112",
    issue_date="2020-01-01", expiry_date="2030-01-01", nationality="Republic of Meridian",
)


def _build_missing_evidence_case():
    application = {"submitted_name": "Priya Nair", "submitted_dob": "1988-05-20", "submitted_address": None}
    # A document missing document_number and expiry_date entirely -- a genuine
    # extraction shortfall, not a formatting variant.
    doc = _evidence("EVAL-MISSING-PASSPORT", DocumentType.PASSPORT, full_name="Priya Nair", date_of_birth="1988-05-20")
    return application, [doc], {}, {"EVAL-MISSING-PASSPORT": ("REVIEW", ["INSUFFICIENT_MANDATORY_FIELDS"])}


def _build_contradictory_evidence_case():
    application = {"submitted_name": "Rohan Iyer", "submitted_dob": "1990-01-01", "submitted_address": None}
    doc1 = _evidence(
        "EVAL-CONTRA-PASSPORT", DocumentType.PASSPORT, full_name="Rohan Iyer", date_of_birth="1990-01-01",
        document_number="PXT800221", issue_date="2020-01-01", expiry_date="2030-01-01",
    )
    # Same person, same document set, but a genuinely contradictory DOB on the second document.
    doc2 = _evidence(
        "EVAL-CONTRA-NID", DocumentType.NATIONAL_ID, full_name="Rohan Iyer", date_of_birth="1991-07-15",
        document_number="MID-1122-3344", issue_date="2020-01-01", expiry_date="2030-01-01",
        address="4 Example Road, Meridian City",
    )
    return application, [doc1, doc2], {}, {
        "EVAL-CONTRA-PASSPORT": ("APPROVE", ["BASELINE_RULES_PASSED"]),
        "EVAL-CONTRA-NID": ("APPROVE", ["BASELINE_RULES_PASSED"]),
    }


def _build_adversarial_unknown_type_case():
    application = {"submitted_name": "Test Subject", "submitted_dob": "1995-03-03", "submitted_address": None}
    # A document type this system has never seen, with an otherwise-plausible field set.
    doc = _evidence(
        "EVAL-ADV-UNKNOWNTYPE", DocumentType.UNKNOWN, full_name="Test Subject", date_of_birth="1995-03-03",
        document_number="XX-000000", expiry_date="2030-01-01",
    )
    return application, [doc], {}, {"EVAL-ADV-UNKNOWNTYPE": ("REVIEW", ["MANUAL_REVIEW_REQUIRED"])}


def _build_adversarial_empty_case():
    # Zero documents at all -- the most degenerate input this pipeline can receive.
    application = {"submitted_name": None, "submitted_dob": None, "submitted_address": None}
    return application, [], {}, {}


def build_eval_cases() -> list[EvalCase]:
    ground_truth_fields = ["full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "address", "nationality"]

    cases = [
        EvalCase(
            case_id="EVAL-GOLDEN-CASE-001", category="golden",
            description="Clean, fully-consistent multi-document case (happy path).",
            source="repository", repo_case_id="CASE-001", expected_decision="APPROVE",
            expected_identity_status="EXACT",
            ground_truth_document_ids=["CASE-001-PASSPORT", "CASE-001-NID", "CASE-001-DL"],
        ),
        EvalCase(
            case_id="EVAL-NOISY-CASE-002", category="noisy",
            description="Degraded OCR quality markers present; fields still fully extracted.",
            source="repository", repo_case_id="CASE-002", expected_decision="REVIEW",
            expected_identity_status="EXACT",
            ground_truth_document_ids=["CASE-002-PASSPORT", "CASE-002-NID"],
        ),
        EvalCase(
            case_id="EVAL-ROTATED-CASE-003", category="rotated",
            description="Rotated-capture marker present on one document.",
            source="repository", repo_case_id="CASE-003", expected_decision="REVIEW",
            expected_identity_status="EXACT",
            ground_truth_document_ids=["CASE-003-DL", "CASE-003-PASSPORT"],
        ),
        EvalCase(
            case_id="EVAL-EXPIRED-CASE-004", category="expired",
            description="One document is expired relative to the frozen reference date.",
            source="repository", repo_case_id="CASE-004", expected_decision="REJECT",
            expected_identity_status="EXACT",
            ground_truth_document_ids=["CASE-004-PASSPORT", "CASE-004-NID"],
        ),
        EvalCase(
            case_id="EVAL-IDVAR-CASE-005", category="identity_variation",
            description="Name variation across submitted/passport/NID, with real OCR-style corruption on the NID.",
            source="repository", repo_case_id="CASE-005", expected_decision="REVIEW",
            expected_identity_status="CONFLICT", should_have_identity_conflict=True,
            ground_truth_document_ids=["CASE-005-PASSPORT", "CASE-005-NID"],
        ),
        EvalCase(
            case_id="EVAL-OCR-CASE-005-NID", category="ocr_corrupted",
            description="Same OCR-corrupted document as above, evaluated specifically for extraction fidelity.",
            source="repository", repo_case_id="CASE-005",
            ground_truth_document_ids=["CASE-005-NID"],
        ),
        EvalCase(
            case_id="EVAL-FRAUD-CASE-006", category="fraud_tampering",
            description="Synthetic tamper-fixture marker present on one document.",
            source="repository", repo_case_id="CASE-006", expected_decision="REJECT",
            expected_identity_status="EXACT", should_have_identity_conflict=False,
            ground_truth_document_ids=["CASE-006-PASSPORT", "CASE-006-DL"],
        ),
        EvalCase(
            case_id="EVAL-MISSING-EVIDENCE-01", category="missing_evidence",
            description="A document missing document_number and expiry_date entirely (synthetic; n=1).",
            source="synthetic", build_synthetic=_build_missing_evidence_case,
            expected_decision="REVIEW", expected_identity_status="INSUFFICIENT_EVIDENCE",
        ),
        EvalCase(
            case_id="EVAL-CONTRADICTORY-01", category="contradictory_evidence",
            description="Same name, genuinely contradictory date_of_birth across two documents (synthetic; n=1).",
            source="synthetic", build_synthetic=_build_contradictory_evidence_case,
            expected_decision="REJECT", expected_identity_status="CONFLICT", should_have_identity_conflict=True,
        ),
        EvalCase(
            case_id="EVAL-ADVERSARIAL-UNKNOWN-TYPE", category="adversarial_malformed",
            description="Unrecognized document type with an otherwise-plausible field set (synthetic; n=1).",
            source="synthetic", build_synthetic=_build_adversarial_unknown_type_case,
            expected_decision="REVIEW",
        ),
        EvalCase(
            case_id="EVAL-ADVERSARIAL-EMPTY-CASE", category="adversarial_malformed",
            description="Zero documents at all -- the most degenerate input the pipeline can receive (synthetic; n=1).",
            source="synthetic", build_synthetic=_build_adversarial_empty_case,
            # Verified by direct execution, not assumed: every identity attribute has
            # zero comparable sources (INSUFFICIENT_EVIDENCE), which is itself a risk
            # factor under P5's policy -- the system does not default to a blind
            # APPROVE on empty input, it correctly escalates to REVIEW.
            expected_decision="REVIEW",
        ),
    ]
    return cases


GROUND_TRUTH_FIELDS = ["full_name", "date_of_birth", "document_number", "issue_date", "expiry_date", "address", "nationality"]
