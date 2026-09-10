"""Consolidated component version metadata (P9 requirement 8) -- what an auditor needs
to reconstruct exactly which logic version produced a given decision, without reading
source code. Pulls existing version constants where a component already versions
itself (decision_policy, evidence_validation's per-rule rule_version); assigns an
explicit version to every other component that did not previously need one for its own
purposes but does need one for reconstruction.
"""

from ..decision_policy.engine import POLICY_VERSION
from ..document_intelligence.sidecar_provider import DeterministicSidecarProvider
from ..evidence_validation.checks import RULE_VERSION as EVIDENCE_VALIDATION_RULE_VERSION
from ..fraud_signals.provider import DeterministicMarkerForensicsProvider
from ..identity_resolution.matching import NAME_FUZZY_THRESHOLD

IDENTITY_RESOLUTION_VERSION = "1.0.0"  # matching.py's rule set (exact/normalized/initials/fuzzy/conflict)


def component_versions() -> dict[str, str]:
    """A flat, JSON-serializable map: component -> version/identifier string.
    Deliberately flat (not nested) so it renders directly into DecisionLineage and
    into a log line without further transformation."""
    return {
        "decision_policy": POLICY_VERSION,
        "evidence_validation": EVIDENCE_VALIDATION_RULE_VERSION,
        "identity_resolution": f"{IDENTITY_RESOLUTION_VERSION} (fuzzy_threshold={NAME_FUZZY_THRESHOLD})",
        "document_intelligence_provider": DeterministicSidecarProvider.name,
        "fraud_forensics_provider": DeterministicMarkerForensicsProvider.name,
    }
