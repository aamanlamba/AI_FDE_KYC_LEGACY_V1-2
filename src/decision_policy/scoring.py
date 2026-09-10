"""Descriptive-only numeric summaries for analyst context.

Neither evidence_strength nor uncertainty drives policy_outcome — the policy decision
comes solely from RiskFactor.triggers_hard_stop (see engine.py). These scores exist to
satisfy RiskAssessment's "evidence strength" / "uncertainty" fields with something more
informative than a factor count, while keeping requirement 3 (never conflate extraction
confidence with identity risk): evidence_strength blends extraction-layer field
confidence with identity-match strength as two clearly separate, documented
components, not a single undifferentiated number, and identity risk itself is reported
separately again via RiskFactor entries and identity_conflict_count.

Both scores are deterministic heuristics, range [0, 1], and are NOT calibrated
probabilities (per requirement 7) -- they are not derived from any observed outcome
distribution and must not be interpreted as one.
"""

from ..evidence_validation.models import ValidationStatus
from ..identity_resolution import MatchStatus
from .models import EvidenceBundle

_IDENTITY_STATUS_SCORE = {
    MatchStatus.EXACT: 1.0,
    MatchStatus.NORMALIZED_MATCH: 0.95,
    MatchStatus.FUZZY_MATCH: 0.6,
    MatchStatus.INSUFFICIENT_EVIDENCE: 0.4,
    MatchStatus.CONFLICT: 0.0,
}


def compute_evidence_strength(bundle: EvidenceBundle) -> float:
    """Mean of: (a) extraction-layer field confidence across all documents, and
    (b) identity-resolution match strength. Two explicitly separate components,
    averaged only at the end -- extraction confidence is never used as a proxy for
    identity risk, or vice versa."""
    field_confidences = [
        field.confidence
        for doc in bundle.documents
        for field in doc.evidence.fields.values()
        if field.value is not None
    ]
    extraction_component = sum(field_confidences) / len(field_confidences) if field_confidences else 0.0

    identity_component = _IDENTITY_STATUS_SCORE[bundle.identity_resolution.overall_status]

    return round((extraction_component + identity_component) / 2, 3)


def compute_uncertainty(bundle: EvidenceBundle) -> float:
    """Saturating count of missing/unknown/ambiguous evidence signals, scaled to
    [0, 1]. Each contributing signal adds 0.2; caps at 1.0. This is a deterministic,
    documented heuristic, not a calibrated probability of anything."""
    unknown_validation_results = sum(
        1 for doc in bundle.documents for result in doc.validation.results if result.status == ValidationStatus.UNKNOWN
    )
    insufficient_identity_attributes = sum(
        1 for ac in bundle.identity_resolution.attribute_comparisons if ac.status == MatchStatus.INSUFFICIENT_EVIDENCE
    )
    unreadable_documents = sum(1 for doc in bundle.documents if doc.evidence.quality.value == "incomplete_unreadable")

    signal_count = unknown_validation_results + insufficient_identity_attributes + unreadable_documents
    return round(min(1.0, signal_count * 0.2), 3)
