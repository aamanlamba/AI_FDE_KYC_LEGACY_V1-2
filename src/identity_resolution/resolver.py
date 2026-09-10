from ..document_intelligence import DocumentEvidence
from .matching import compare_addresses, compare_dob, compare_names, worst_status
from .models import (
    AttributeComparison,
    AttributeSource,
    IdentityResolutionResult,
    MatchStatus,
    PairwiseComparison,
)
from .normalization import normalize_address, normalize_dob, normalize_name

APPLICATION_SOURCE_ID = "SUBMITTED_APPLICATION"

# document_number is intentionally NOT compared cross-document here: different
# document types legitimately carry different identifiers for the same person
# (a passport number differs from a national ID number by design). It remains
# available via normalize_document_number() for future duplicate-document checks,
# which are a distinct concern from identity attribute matching.
_ATTRIBUTE_COMPARATORS = {
    "full_name": (compare_names, normalize_name),
    "date_of_birth": (compare_dob, normalize_dob),
    "address": (compare_addresses, normalize_address),
}

_STATUS_SCORE = {
    MatchStatus.EXACT: 1.0,
    MatchStatus.NORMALIZED_MATCH: 0.95,
    MatchStatus.FUZZY_MATCH: 0.6,
    MatchStatus.INSUFFICIENT_EVIDENCE: 0.4,
    MatchStatus.CONFLICT: 0.0,
}


def _document_field_value(evidence: DocumentEvidence, field_name: str) -> str | None:
    field = evidence.fields.get(field_name)
    return field.value if field is not None else None


def _attribute_reason_codes(attribute: str, status: MatchStatus) -> list[str]:
    prefix = attribute.upper()
    if status == MatchStatus.CONFLICT:
        return [f"{prefix}_CONFLICT"]
    if status == MatchStatus.INSUFFICIENT_EVIDENCE:
        return [f"{prefix}_INSUFFICIENT_EVIDENCE"]
    if status == MatchStatus.FUZZY_MATCH:
        return [f"{prefix}_FUZZY_MATCH"]
    return [f"{prefix}_CONSISTENT"]


def _compare_attribute(attribute: str, sources: list[AttributeSource]) -> AttributeComparison:
    compare_fn, _normalize_fn = _ATTRIBUTE_COMPARATORS[attribute]
    usable = [s for s in sources if s.raw_value is not None]
    supporting_documents = sorted(s.source_id for s in usable if s.source_id != APPLICATION_SOURCE_ID)

    if len(usable) < 2:
        return AttributeComparison(
            attribute=attribute,
            sources=sources,
            pairwise=[],
            status=MatchStatus.INSUFFICIENT_EVIDENCE,
            supporting_documents=supporting_documents,
            reason_codes=_attribute_reason_codes(attribute, MatchStatus.INSUFFICIENT_EVIDENCE),
        )

    pairwise: list[PairwiseComparison] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = usable[i], usable[j]
            status, similarity, notes = compare_fn(a.raw_value, b.raw_value)
            pairwise.append(
                PairwiseComparison(
                    source_a=a.source_id, source_b=b.source_id, status=status, similarity=similarity, notes=notes
                )
            )

    status = worst_status([p.status for p in pairwise])
    return AttributeComparison(
        attribute=attribute,
        sources=sources,
        pairwise=pairwise,
        status=status,
        supporting_documents=supporting_documents,
        reason_codes=_attribute_reason_codes(attribute, status),
    )


def _overall_confidence(attribute_comparisons: list[AttributeComparison], overall_status: MatchStatus) -> float:
    if overall_status == MatchStatus.CONFLICT:
        # A confirmed contradiction is never averaged away by other clean attributes.
        return 0.0
    scores = [_STATUS_SCORE[ac.status] for ac in attribute_comparisons]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 3)


def resolve_identity(
    case_id: str, application: dict, documents_evidence: list[DocumentEvidence]
) -> IdentityResolutionResult:
    """Explicitly answer whether the case's independent evidence describes one identity.

    Compares full_name, date_of_birth and address across the submitted application and
    every document's extracted evidence. Deterministic/explainable comparisons (exact,
    normalized, initials, reordering) are always tried before any fuzzy comparison, and
    fuzzy similarity alone is never upgraded to a proof of identity (it stays
    FUZZY_MATCH). A single CONFLICT anywhere in an attribute makes that attribute's
    overall status CONFLICT, regardless of how many other sources agree.
    """
    attribute_comparisons: list[AttributeComparison] = []

    for attribute in ("full_name", "date_of_birth", "address"):
        application_field = {"full_name": "submitted_name", "date_of_birth": "submitted_dob", "address": "submitted_address"}[
            attribute
        ]
        _, normalize_fn = _ATTRIBUTE_COMPARATORS[attribute]
        raw_application_value = application.get(application_field)
        sources = [
            AttributeSource(
                source_id=APPLICATION_SOURCE_ID,
                raw_value=raw_application_value,
                normalized_value=normalize_fn(raw_application_value),
            )
        ]
        for evidence in documents_evidence:
            raw_value = _document_field_value(evidence, attribute)
            if raw_value is None:
                continue
            sources.append(
                AttributeSource(
                    source_id=evidence.document_id,
                    raw_value=raw_value,
                    normalized_value=normalize_fn(raw_value),
                )
            )
        attribute_comparisons.append(_compare_attribute(attribute, sources))

    overall_status = worst_status([ac.status for ac in attribute_comparisons])
    confidence = _overall_confidence(attribute_comparisons, overall_status)

    conflicts = [
        f"{ac.attribute}: {p.source_a} vs {p.source_b} ({'; '.join(p.notes)})"
        for ac in attribute_comparisons
        for p in ac.pairwise
        if p.status == MatchStatus.CONFLICT
    ]

    reason_codes = [f"IDENTITY_{overall_status.value}"]
    for ac in attribute_comparisons:
        reason_codes.extend(ac.reason_codes)

    return IdentityResolutionResult(
        case_id=case_id,
        overall_status=overall_status,
        confidence=confidence,
        attribute_comparisons=attribute_comparisons,
        conflicts=conflicts,
        supporting_documents=sorted({e.document_id for e in documents_evidence}),
        reason_codes=reason_codes,
    )
