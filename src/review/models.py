from enum import Enum

from pydantic import BaseModel, Field


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ReviewPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# OPEN -> IN_REVIEW -> {RESOLVED, ESCALATED}. RESOLVED/ESCALATED are terminal: no
# transition reopens a review in this workshop-scoped workflow. Any pair not listed
# here (including a state transitioning to itself) is rejected by ReviewStore.
ALLOWED_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.OPEN: {ReviewStatus.IN_REVIEW},
    ReviewStatus.IN_REVIEW: {ReviewStatus.RESOLVED, ReviewStatus.ESCALATED},
    ReviewStatus.RESOLVED: set(),
    ReviewStatus.ESCALATED: set(),
}


class EvidenceSummary(BaseModel):
    """A concise, deterministic snapshot -- not a live reference. Captured once when
    the review is opened; never mutated afterward (see ReviewCase docstring)."""

    document_count: int
    document_types: list[str]
    key_fields: dict[str, dict[str, str | None]]  # document_id -> {field_name: value}


class ReviewCase(BaseModel):
    """A durable, immutable-once-created snapshot of the evidence that triggered
    human review, plus its current workflow state. Analyst corrections are captured
    only in ReviewAuditEntry.correction -- they are annotations layered on top of this
    snapshot, never a rewrite of it (requirement: no silent rewriting of evidence).
    """

    review_id: str
    case_id: str
    trigger: str
    priority: ReviewPriority
    evidence_summary: EvidenceSummary
    discrepancies: list[str]
    failed_validations: list[str]
    fraud_signals: list[str]
    reason_codes: list[str]
    status: ReviewStatus
    created_at: str
    policy_version: str
    reviewer_summary: str


class ReviewAuditEntry(BaseModel):
    """One immutable, append-only record of an analyst action. The review_audit_log
    table this maps to is insert-only -- no code path updates or deletes a row."""

    review_id: str
    analyst_action: str
    correction: str | None = None
    rationale: str
    timestamp: str
    prior_state: ReviewStatus
    new_state: ReviewStatus


class ReviewTransitionRequest(BaseModel):
    new_status: ReviewStatus
    analyst_action: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    correction: str | None = Field(default=None, max_length=2000)
