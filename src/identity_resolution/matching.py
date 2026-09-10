import difflib

from .models import MatchStatus
from .normalization import (
    normalize_address,
    normalize_dob,
    normalize_name,
    tokens_compatible,
    tokens_match_ignoring_order,
)

# Calibrated against the shipped synthetic dataset (see docs/assessment for the
# similarity values behind this choice): 0.75 separates plausible spelling/OCR
# variants of the same name (observed ratios 0.81-0.87) from genuinely different
# names (observed ratios <=0.74), with margin on both sides.
NAME_FUZZY_THRESHOLD = 0.75
ADDRESS_FUZZY_THRESHOLD = 0.75

STATUS_RANK = {
    MatchStatus.CONFLICT: 0,
    MatchStatus.INSUFFICIENT_EVIDENCE: 1,
    MatchStatus.FUZZY_MATCH: 2,
    MatchStatus.NORMALIZED_MATCH: 3,
    MatchStatus.EXACT: 4,
}


def worst_status(statuses: list[MatchStatus]) -> MatchStatus:
    """The most-concerning status wins; contradictions are never averaged away."""
    if not statuses:
        return MatchStatus.INSUFFICIENT_EVIDENCE
    return min(statuses, key=lambda s: STATUS_RANK[s])


def _similarity(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def compare_names(raw_a: str | None, raw_b: str | None) -> tuple[MatchStatus, float | None, list[str]]:
    if raw_a is None or raw_b is None:
        return MatchStatus.INSUFFICIENT_EVIDENCE, None, ["MISSING_VALUE"]
    if raw_a == raw_b:
        return MatchStatus.EXACT, 1.0, []

    norm_a, norm_b = normalize_name(raw_a), normalize_name(raw_b)
    if norm_a == norm_b:
        return MatchStatus.NORMALIZED_MATCH, 1.0, ["NORMALIZED_EQUAL"]

    tokens_a, tokens_b = norm_a.split(), norm_b.split()
    if tokens_compatible(tokens_a, tokens_b):
        return MatchStatus.NORMALIZED_MATCH, 1.0, ["INITIAL_COMPATIBLE"]
    if tokens_match_ignoring_order(tokens_a, tokens_b):
        return MatchStatus.NORMALIZED_MATCH, 1.0, ["TOKEN_ORDER_DIFFERENT"]

    similarity = _similarity(norm_a, norm_b)
    if similarity >= NAME_FUZZY_THRESHOLD:
        return MatchStatus.FUZZY_MATCH, similarity, [f"SIMILARITY={similarity}"]
    return MatchStatus.CONFLICT, similarity, [f"SIMILARITY={similarity}"]


def compare_dob(raw_a: str | None, raw_b: str | None) -> tuple[MatchStatus, float | None, list[str]]:
    if raw_a is None or raw_b is None:
        return MatchStatus.INSUFFICIENT_EVIDENCE, None, ["MISSING_VALUE"]

    norm_a, norm_b = normalize_dob(raw_a), normalize_dob(raw_b)
    if norm_a is None or norm_b is None:
        return MatchStatus.INSUFFICIENT_EVIDENCE, None, ["UNPARSEABLE_DATE"]
    if norm_a != norm_b:
        # Dates are exact-or-contradiction: no legitimate "fuzzy" date variance exists.
        return MatchStatus.CONFLICT, 0.0, [f"DOB_MISMATCH:{norm_a}!={norm_b}"]
    return (MatchStatus.EXACT if raw_a == raw_b else MatchStatus.NORMALIZED_MATCH), 1.0, []


def compare_addresses(raw_a: str | None, raw_b: str | None) -> tuple[MatchStatus, float | None, list[str]]:
    if raw_a is None or raw_b is None:
        return MatchStatus.INSUFFICIENT_EVIDENCE, None, ["MISSING_VALUE"]
    if raw_a == raw_b:
        return MatchStatus.EXACT, 1.0, []

    norm_a, norm_b = normalize_address(raw_a), normalize_address(raw_b)
    if norm_a == norm_b:
        return MatchStatus.NORMALIZED_MATCH, 1.0, ["NORMALIZED_EQUAL"]

    similarity = _similarity(norm_a, norm_b)
    if similarity >= ADDRESS_FUZZY_THRESHOLD:
        return MatchStatus.FUZZY_MATCH, similarity, [f"SIMILARITY={similarity}"]
    return MatchStatus.CONFLICT, similarity, [f"SIMILARITY={similarity}"]
