from ..policy import Decision
from .factors import derive_risk_factors
from .models import EvidenceBundle, RiskAssessment, RiskFactor, RiskFactorCategory
from .scoring import compute_evidence_strength, compute_uncertainty

# Bump this whenever the rules below change. Decisions are reproducible from retained
# evidence (see EvidenceBundle) plus this version: re-running the same policy_version
# against the same evidence layers must reproduce the same policy_outcome.
POLICY_VERSION = "1.0.0"


def _decide(risk_factors: list[RiskFactor]) -> tuple[Decision, bool]:
    """Explicit, inspectable, deterministic policy -- no weighted scoring.

    Hard-stop conditions are defined separately from review conditions (requirement 8):
    a RiskFactor either triggers_hard_stop or it doesn't; that boolean is set once,
    where the factor is derived (see factors.py), and is the only thing this function
    reads. If any factor is a hard stop -> REJECT. Otherwise, any factor at all ->
    REVIEW (every factor that reaches this list represents a deviation from clean
    evidence by construction -- see factors.py, which only emits a factor when
    something is NOT normal/clean). No factors -> APPROVE.
    """
    hard_stop = any(factor.triggers_hard_stop for factor in risk_factors)
    if hard_stop:
        return "REJECT", True
    if risk_factors:
        return "REVIEW", False
    return "APPROVE", False


def _reason_codes(risk_factors: list[RiskFactor]) -> list[str]:
    """Each factor labels itself HARD_STOP or REVIEW by its own triggers_hard_stop flag
    -- so on a REJECT outcome caused by one hard-stop factor, a co-occurring merely-
    review-level factor is still visible as REVIEW:<category>, not silently absorbed."""
    if not risk_factors:
        return ["POLICY_APPROVED_NO_RISK_FACTORS"]
    return sorted({
        f"{'HARD_STOP' if factor.triggers_hard_stop else 'REVIEW'}:{factor.category.value}"
        for factor in risk_factors
    })


def _explanation(bundle: EvidenceBundle, risk_factors: list[RiskFactor], outcome: Decision) -> str:
    if not risk_factors:
        return (
            f"Case {bundle.case_id}: no risk factors were found across document decisions, "
            f"identity resolution, evidence validation, or fraud signals. Policy outcome: APPROVE."
        )
    hard_stops = [f for f in risk_factors if f.triggers_hard_stop]
    by_category: dict[str, int] = {}
    for factor in risk_factors:
        by_category[factor.category.value] = by_category.get(factor.category.value, 0) + 1
    category_summary = ", ".join(f"{count}x {category}" for category, count in sorted(by_category.items()))
    if hard_stops:
        hard_stop_summary = "; ".join(f"{f.factor_id}: {f.description}" for f in hard_stops)
        return (
            f"Case {bundle.case_id}: {len(risk_factors)} risk factor(s) found ({category_summary}). "
            f"Policy outcome: REJECT, triggered by {len(hard_stops)} hard-stop factor(s): {hard_stop_summary}"
        )
    return (
        f"Case {bundle.case_id}: {len(risk_factors)} risk factor(s) found ({category_summary}), "
        f"none of which is a hard-stop condition. Policy outcome: REVIEW."
    )


def assess_case_risk(bundle: EvidenceBundle) -> RiskAssessment:
    risk_factors = derive_risk_factors(bundle)
    outcome, hard_stop_triggered = _decide(risk_factors)

    validation_failure_count = sum(1 for f in risk_factors if f.category == RiskFactorCategory.VALIDATION_FAILURE)
    identity_conflict_count = sum(
        1 for f in risk_factors if f.category in (RiskFactorCategory.IDENTITY_CONFLICT, RiskFactorCategory.IDENTITY_UNCERTAINTY)
    )
    fraud_signal_count = sum(1 for f in risk_factors if f.category == RiskFactorCategory.FRAUD_SIGNAL)

    return RiskAssessment(
        case_id=bundle.case_id,
        policy_version=POLICY_VERSION,
        risk_factors=risk_factors,
        evidence_strength=compute_evidence_strength(bundle),
        uncertainty=compute_uncertainty(bundle),
        validation_failure_count=validation_failure_count,
        identity_conflict_count=identity_conflict_count,
        fraud_signal_count=fraud_signal_count,
        hard_stop_triggered=hard_stop_triggered,
        policy_outcome=outcome,
        reason_codes=_reason_codes(risk_factors),
        explanation=_explanation(bundle, risk_factors, outcome),
    )
