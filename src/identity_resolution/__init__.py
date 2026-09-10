from .matching import compare_addresses, compare_dob, compare_names, worst_status
from .models import (
    AttributeComparison,
    AttributeSource,
    IdentityResolutionResult,
    MatchStatus,
    PairwiseComparison,
)
from .normalization import (
    normalize_address,
    normalize_dob,
    normalize_document_number,
    normalize_name,
)
from .resolver import resolve_identity

__all__ = [
    "MatchStatus",
    "AttributeSource",
    "PairwiseComparison",
    "AttributeComparison",
    "IdentityResolutionResult",
    "resolve_identity",
    "compare_names",
    "compare_dob",
    "compare_addresses",
    "worst_status",
    "normalize_name",
    "normalize_dob",
    "normalize_address",
    "normalize_document_number",
]
