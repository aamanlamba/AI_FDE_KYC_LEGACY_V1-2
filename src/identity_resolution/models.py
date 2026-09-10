from enum import Enum

from pydantic import BaseModel, Field


class MatchStatus(str, Enum):
    EXACT = "EXACT"
    NORMALIZED_MATCH = "NORMALIZED_MATCH"
    FUZZY_MATCH = "FUZZY_MATCH"
    CONFLICT = "CONFLICT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AttributeSource(BaseModel):
    """One value contributed to an attribute comparison, raw and normalized side by side.

    Original evidence is never discarded: raw_value is always the untouched value from
    its source (submitted application field, or a document's extracted evidence field).
    """

    source_id: str
    raw_value: str | None
    normalized_value: str | None


class PairwiseComparison(BaseModel):
    source_a: str
    source_b: str
    status: MatchStatus
    similarity: float | None = None
    notes: list[str] = Field(default_factory=list)


class AttributeComparison(BaseModel):
    attribute: str
    sources: list[AttributeSource]
    pairwise: list[PairwiseComparison]
    status: MatchStatus
    supporting_documents: list[str]
    reason_codes: list[str] = Field(default_factory=list)


class IdentityResolutionResult(BaseModel):
    """Explicit answer to: do the independent pieces of evidence for this case
    consistently describe the same claimed identity?

    This is evidence-strength reporting only. It does not decide APPROVE/REVIEW/REJECT
    — that remains src/rules.py's case-aggregation policy today, pending a later
    risk-policy stage.
    """

    case_id: str
    overall_status: MatchStatus
    confidence: float = Field(ge=0.0, le=1.0)
    attribute_comparisons: list[AttributeComparison]
    conflicts: list[str] = Field(default_factory=list)
    supporting_documents: list[str]
    reason_codes: list[str] = Field(default_factory=list)
