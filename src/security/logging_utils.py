"""A narrow logging helper that only accepts an explicit allowlist of field NAMES
(operational identifiers, statuses, counts) -- never arbitrary values. This makes
"accidentally logged a name/DOB" a call-site error that is easy to spot in review
(an unrecognized kwarg raises immediately) rather than a silent, hard-to-audit leak.

This does not replace normal application logging (src/app.py's correlation
middleware already logs only method/path/status/correlation_id and is unaffected);
it exists for any future call site that needs to log something about a case/review/
document without risking PII exposure by construction.
"""

import logging

# Deliberately small and explicit. Every one of these is an operational identifier or
# a coarse status/category -- never an identity attribute (name, DOB, address,
# document number) or free-text evidence content (see docs/security/privacy_data_flow.md
# for the operational-identifier / identity-attribute / evidence-content distinction).
_ALLOWED_FIELDS = frozenset({
    "case_id", "document_id", "review_id", "correlation_id",
    "decision", "status", "prior_state", "new_state", "category", "severity",
    "count", "reason_code", "rule_id", "event",
})


def log_operational_event(logger: logging.Logger, event: str, **fields: object) -> None:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(
            f"log_operational_event: field(s) {sorted(unknown)} are not in the operational-identifier "
            f"allowlist -- this looks like it might log identity/evidence content; add the field to "
            f"_ALLOWED_FIELDS only after confirming it never carries PII, or use a different field."
        )
    pairs = " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))
    logger.info("event=%s %s", event, pairs)
