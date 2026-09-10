"""Strict allowlist validation for every operational identifier this service accepts
from a caller (document_id, case_id, review_id, ...).

This replaces a denylist approach (reject '/', '\\', '..') with an allowlist: only
letters, digits, underscore and hyphen are accepted, the value must start with a
letter, and length is bounded. A denylist is only ever as good as the list of things
someone thought to block (P0's finding was already narrow: it only ever needed to stop
'/','\\','..'); an allowlist is safe by construction against traversal, null-byte,
control-character, and unicode-homoglyph tricks a denylist would need to be extended
for one at a time.
"""

import re

MAX_IDENTIFIER_LENGTH = 80
IDENTIFIER_PATTERN_STR = r"^[A-Za-z][A-Za-z0-9_-]{0,%d}$" % (MAX_IDENTIFIER_LENGTH - 1)
_IDENTIFIER_PATTERN = re.compile(IDENTIFIER_PATTERN_STR)


def validate_identifier(value: str, *, label: str = "identifier") -> str:
    """Returns value unchanged if it is a safe operational identifier; raises
    ValueError otherwise. Never returns a modified/sanitized value -- an identifier
    either is safe to use as-is, or it is rejected outright."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid {label}: must be a non-empty string")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"invalid {label}: exceeds maximum length of {MAX_IDENTIFIER_LENGTH}")
    if not _IDENTIFIER_PATTERN.match(value):
        raise ValueError(f"invalid {label}: must match ^[A-Za-z][A-Za-z0-9_-]*$")
    return value
