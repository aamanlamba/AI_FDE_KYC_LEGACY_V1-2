"""Utilities for handling document-derived content safely wherever it is composed
into a human-readable or logged string.

Rule: document content (OCR text, extracted field values) is DATA, never a trusted
system instruction, and never safe to embed verbatim into a log line or narrative
string without sanitization -- a crafted field value containing newlines or control
characters could otherwise forge additional log entries ("log injection") or corrupt
terminal output. This module never alters retained evidence (EvidenceField.value is
never touched); it only governs what is safe to print/log/narrate.
"""

import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RUN = re.compile(r"\s+")
DEFAULT_MAX_DISPLAY_LENGTH = 200


def sanitize_for_display(value: str | None, *, max_length: int = DEFAULT_MAX_DISPLAY_LENGTH) -> str:
    """Collapses newlines/control characters to single spaces and caps length.

    Safe to embed in a log line, an API explanation string, or a reviewer narrative:
    the result can never itself look like a second log line or carry a raw control
    sequence, regardless of what the original document-derived value contained.
    """
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    no_control_chars = _CONTROL_CHARS.sub(" ", normalized)
    collapsed = _WHITESPACE_RUN.sub(" ", no_control_chars).strip()
    if len(collapsed) > max_length:
        return collapsed[:max_length] + "…(truncated)"
    return collapsed


def redact_partial(value: str | None, *, keep_first: int = 1) -> str:
    """Partial masking for lower-trust display contexts (e.g. a list view): keeps the
    first `keep_first` characters of each whitespace-separated token, masks the rest.
    'Aarav Mehta' -> 'A**** M****'. Never used for the retained evidence itself, only
    for a display-only projection of it.
    """
    if not value:
        return ""
    tokens = sanitize_for_display(value).split(" ")
    return " ".join(
        token[:keep_first] + "*" * max(len(token) - keep_first, 0) if token else token
        for token in tokens
    )


def mask_tail(value: str | None, *, keep_first: int = 4) -> str:
    """Masks all but the leading characters of a single token value (e.g. a document
    number): 'PXT100184' -> 'PXT1******'."""
    if not value:
        return ""
    cleaned = sanitize_for_display(value)
    if len(cleaned) <= keep_first:
        return cleaned
    return cleaned[:keep_first] + "*" * (len(cleaned) - keep_first)
