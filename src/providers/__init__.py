"""New, not-yet-wired provider integration points (P10 requirement 4) plus the shared
resilience helper they (and any future external adapter) would use.

This package deliberately does NOT re-home the provider interfaces P1-P8 already
established (DocumentIntelligenceProvider in src.document_intelligence,
DocumentForensicsProvider in src.fraud_signals, ReviewSummaryProvider in src.review,
Authorizer in src.security) -- those are co-located with the domain they serve, which
is this repository's established, consistent convention, and moving them would be a
rewrite for organizational aesthetics rather than a fix for a real problem (P10's own
top-line instruction). See docs/architecture/overview.md's provider inventory table
for the complete list across all locations.
"""

from .external_fraud import ExternalFraudSignalProvider, NullExternalFraudSignalProvider
from .external_identity import (
    ExternalIdentityVerificationProvider,
    ExternalIdentityVerificationResult,
    NullExternalIdentityProvider,
)
from .resilience import ProviderTimeoutError, ProviderUnavailableError, call_with_retries

__all__ = [
    "ExternalIdentityVerificationProvider",
    "ExternalIdentityVerificationResult",
    "NullExternalIdentityProvider",
    "ExternalFraudSignalProvider",
    "NullExternalFraudSignalProvider",
    "call_with_retries",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
]
