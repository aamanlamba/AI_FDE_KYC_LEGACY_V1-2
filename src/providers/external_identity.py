"""External identity verification provider interface (P10 requirement 4).

A real deployment would implement this against a government ID registry, credit
bureau, or similar external verification service -- wrapping the network call in
call_with_retries and enforcing timeout_seconds -- without changing any caller.
NullExternalIdentityProvider is the only implementation in this repository.

Deliberately NOT wired into src.service/src.decision_policy in this stage: adding a
new evidence source that could influence a decision is a policy change (src.decision_policy's
domain, P5), not an architecture change. This interface is the documented seam a future
stage would wire in -- introducing it here without consuming it avoids a rewrite that
extends beyond what P10 asks for (architecture, not new decisioning behavior).
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ExternalIdentityVerificationResult(BaseModel):
    status: str  # "MATCHED" / "NOT_MATCHED" / "NOT_IMPLEMENTED"
    provider: str
    detail: str


class ExternalIdentityVerificationProvider(ABC):
    name: str
    timeout_seconds: float = 5.0

    @abstractmethod
    def verify(self, full_name: str, date_of_birth: str, document_number: str) -> ExternalIdentityVerificationResult:
        raise NotImplementedError


class NullExternalIdentityProvider(ExternalIdentityVerificationProvider):
    """Honestly reports that no external identity verification capability is
    configured, rather than fabricating a result -- the same capability-boundary
    honesty as P3's CHECKSUM-SIGNATURE NOT_IMPLEMENTED status."""

    name = "null_external_identity_provider"

    def verify(self, full_name: str, date_of_birth: str, document_number: str) -> ExternalIdentityVerificationResult:
        return ExternalIdentityVerificationResult(
            status="NOT_IMPLEMENTED",
            provider=self.name,
            detail="No external identity verification service is configured in this offline training repository.",
        )
