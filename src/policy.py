"""Runtime-loaded policy values AND shared, dependency-free domain constants.

A dependency-free leaf module (imports nothing from src.rules / src.document_intelligence
/ src.evidence_validation / src.fraud_signals) so any of them can safely import from it
without creating a cycle.

config/baseline.json is treated as authoritative when it defines a value; otherwise
these built-in defaults (matching the repository's historical hard-coded values)
apply, so the service still runs offline if the config file is missing or partial.

P10 note: PATTERNS (document-number format per type) and TAMPER_MARKER (the synthetic
tamper-fixture marker) live here, not in src/rules.py, even though src/rules.py is
their oldest consumer. Before this stage, src/document_intelligence/, src/evidence_validation/,
and src/fraud_signals/ all imported these from src/rules.py -- conceptually decisioning's
own module -- purely to avoid duplicating the constants, which is a layering violation
(extraction/validation/fraud depending on decisioning for values that belong to none of
them specifically). Moving them to this already-neutral, already-shared leaf module
removes that inappropriate coupling without changing a single value. This is a pure
constant relocation: no behavior changes, verified by the full regression suite passing
unchanged before and after.
"""

from pathlib import Path
from typing import Literal
import json
import re

Decision = Literal["APPROVE", "REVIEW", "REJECT"]

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "baseline.json"

_DEFAULT_MANDATORY_FIELDS = ("full_name", "date_of_birth", "document_number", "expiry_date")
_DEFAULT_SUPPORTED_DOCUMENT_TYPES = ("passport", "national_id", "driving_licence")
_DEFAULT_MIN_FIELD_COMPLETENESS_FOR_APPROVE = 0.75


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_config = _load_config()

MANDATORY_FIELDS: tuple[str, ...] = tuple(_config.get("mandatory_fields", _DEFAULT_MANDATORY_FIELDS))
SUPPORTED_DOCUMENT_TYPES: tuple[str, ...] = tuple(
    _config.get("supported_document_types", _DEFAULT_SUPPORTED_DOCUMENT_TYPES)
)
MIN_FIELD_COMPLETENESS_FOR_APPROVE: float = float(
    _config.get("min_field_completeness_for_approve", _DEFAULT_MIN_FIELD_COMPLETENESS_FOR_APPROVE)
)
CONFIG_SOURCE: str = "config/baseline.json" if _config else "built-in defaults (config/baseline.json missing or empty)"

# Structural facts about the synthetic document formats -- not business-policy
# thresholds (those, like MIN_FIELD_COMPLETENESS_FOR_APPROVE above, come from config).
# Shared by src.rules (decisioning), src.document_intelligence (classification/
# extraction), src.evidence_validation (format checks), and src.fraud_signals
# (the tamper-marker registry) -- none of which "owns" the other.
PATTERNS: dict[str, re.Pattern] = {
    "passport": re.compile(r"^PXT\d{6}$"),
    "national_id": re.compile(r"^MID-\d{4}-\d{4}$"),
    "driving_licence": re.compile(r"^MDL-\d{6}$"),
}
TAMPER_MARKER = "ALTERED_TEXT_REGION_DETECTED"  # synthetic test-fixture marker
