from ..evidence_validation.models import Severity
from ..policy import TAMPER_MARKER
from .models import FraudCategory

# Each entry: marker substring -> (category, severity, reason_code, explanation).
#
# "where present" (P4 requirement 4): only markers that actually occur in this
# training repository's synthetic data are registered here. This is a literal text
# substring scan against the deterministic OCR sidecar -- explicitly NOT pixel-level
# image forensics (see src/fraud_signals/provider.py) -- and its source is labeled
# accordingly on every FraudSignal it produces, per requirement 3 ("label their source
# accurately"). Adding a future marker means adding one registry entry; no downstream
# code needs to change.
KNOWN_SIDECAR_ANOMALY_MARKERS: dict[str, tuple[FraudCategory, Severity, str, str]] = {
    TAMPER_MARKER: (
        FraudCategory.TAMPER_MARKER,
        Severity.CRITICAL,
        "TAMPER_MARKER_DETECTED",
        f"The deterministic OCR sidecar contains the synthetic tamper-fixture marker "
        f"'{TAMPER_MARKER}'. This is a training-data fixture signal, not a cryptographic "
        f"or pixel-level forensic finding.",
    ),
}
