"""External fraud-detection service provider interface (P10 requirement 4) --
distinct from src.fraud_signals.DocumentForensicsProvider (P4), which is about
document-tampering signals derivable from the supplied evidence itself. This
interface is for a third-party fraud-scoring/velocity/device-risk service a real
deployment might call, external to this system's own evidence entirely.

NullExternalFraudSignalProvider is the only implementation in this repository, and
returns no signals rather than fabricating any -- consistent with src.fraud_signals'
own rule (never invent a finding; see docs/data_dictionary.md's fraud-signals section).
Not wired into src.service/src.decision_policy in this stage for the same reason as
external_identity.py: consuming a new signal source is a policy decision, not an
architecture change.
"""

from abc import ABC, abstractmethod

from ..fraud_signals import FraudSignal


class ExternalFraudSignalProvider(ABC):
    name: str
    timeout_seconds: float = 5.0

    @abstractmethod
    def assess(self, case_id: str) -> list[FraudSignal]:
        """Returns zero or more FraudSignal findings from an external service. An
        empty list means "no signal available", not "confirmed clean" -- the same
        evidence-not-verdict distinction every provider interface in this repository
        maintains."""
        raise NotImplementedError


class NullExternalFraudSignalProvider(ExternalFraudSignalProvider):
    name = "null_external_fraud_signal_provider"

    def assess(self, case_id: str) -> list[FraudSignal]:
        return []
