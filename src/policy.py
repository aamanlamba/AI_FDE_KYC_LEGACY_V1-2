"""Runtime-loaded policy values. A dependency-free leaf module (no imports from
src.rules / src.document_intelligence / src.evidence_validation) so it can be safely
imported by any of them without creating a cycle.

config/baseline.json is treated as authoritative when it defines a value; otherwise
these built-in defaults (matching the repository's historical hard-coded values)
apply, so the service still runs offline if the config file is missing or partial.
"""

from pathlib import Path
from typing import Literal
import json

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
