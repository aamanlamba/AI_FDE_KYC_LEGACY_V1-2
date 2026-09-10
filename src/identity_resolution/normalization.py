import re
from datetime import date

_WHITESPACE = re.compile(r"\s+")
_NAME_PUNCTUATION = re.compile(r"[.,'`]")
_ADDRESS_PUNCTUATION = re.compile(r"[.,#]")


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def normalize_name(value: str | None) -> str | None:
    """Case/punctuation/spacing-insensitive form. Never corrects spelling or content."""
    if not value:
        return None
    v = value.upper()
    v = _NAME_PUNCTUATION.sub("", v)
    v = v.replace("-", " ")
    return _collapse_whitespace(v)


def normalize_dob(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def normalize_address(value: str | None) -> str | None:
    if not value:
        return None
    v = value.upper()
    v = _ADDRESS_PUNCTUATION.sub("", v)
    return _collapse_whitespace(v)


def normalize_document_number(value: str | None) -> str | None:
    if not value:
        return None
    return _WHITESPACE.sub("", value.strip().upper())


def tokens_compatible(tokens_a: list[str], tokens_b: list[str]) -> bool:
    """Position-wise: equal, or one side is a single-letter initial of the other.

    Handles 'JOHN A SMITH' vs 'JOHN ANDREW SMITH'. Deterministic and explainable —
    not a similarity score.
    """
    if len(tokens_a) != len(tokens_b):
        return False
    for a, b in zip(tokens_a, tokens_b):
        if a == b:
            continue
        if len(a) == 1 and b.startswith(a):
            continue
        if len(b) == 1 and a.startswith(b):
            continue
        return False
    return True


def tokens_match_ignoring_order(tokens_a: list[str], tokens_b: list[str]) -> bool:
    """Same tokens, different order. Handles 'SMITH JOHN' vs 'JOHN SMITH'."""
    return len(tokens_a) == len(tokens_b) and sorted(tokens_a) == sorted(tokens_b)
