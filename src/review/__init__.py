from .errors import InvalidTransitionError, ReviewNotEligibleError, ReviewNotFoundError
from .models import (
    ALLOWED_TRANSITIONS,
    EvidenceSummary,
    ReviewAuditEntry,
    ReviewCase,
    ReviewPriority,
    ReviewStatus,
    ReviewTransitionRequest,
)
from .store import ReviewRepository, ReviewStore
from .summary import DeterministicReviewSummaryProvider, ReviewSummaryProvider
from .workflow import open_review_case

_default_store: ReviewStore | None = None


def get_default_review_store() -> ReviewStore:
    global _default_store
    if _default_store is None:
        _default_store = ReviewStore()
    return _default_store


__all__ = [
    "ReviewStatus",
    "ReviewPriority",
    "ALLOWED_TRANSITIONS",
    "EvidenceSummary",
    "ReviewCase",
    "ReviewAuditEntry",
    "ReviewTransitionRequest",
    "ReviewRepository",
    "ReviewStore",
    "ReviewSummaryProvider",
    "DeterministicReviewSummaryProvider",
    "ReviewNotFoundError",
    "ReviewNotEligibleError",
    "InvalidTransitionError",
    "open_review_case",
    "get_default_review_store",
]
