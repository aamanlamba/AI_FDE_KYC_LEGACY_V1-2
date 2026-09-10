"""Runs the P1-P5 evidence/decision pipeline directly against constructed
DocumentEvidence, for evaluation cases that have no backing data/ fixtures
(missing evidence, contradictory evidence, adversarial/malformed input, and the
metamorphic/adversarial probes in eval/metamorphic.py).

This deliberately mirrors the composition in src/service.py:verify_case rather than
extending verify_case itself -- the evaluation harness observes and measures the
system under test, it does not modify it. src/service.py is untouched by this stage.
The one thing this cannot exercise is src/rules.py's own per-document decision (that
requires real sidecar text read via src.ocr); callers supply a plausible
legacy_decision/legacy_reason_codes directly, since the point of a synthetic case is to
exercise identity/validation/fraud/decision-policy layers specifically.
"""

from dataclasses import dataclass, field

from src.decision_policy import DocumentEvidenceSummary, RiskAssessment, assess_case_risk, build_evidence_bundle
from src.document_intelligence import DocumentEvidence
from src.evidence_validation import CaseValidationReport, DocumentValidationReport, validate_case, validate_document
from src.fraud_signals import FraudAssessment, assess_case_fraud, assess_document_fraud_signals
from src.identity_resolution import IdentityResolutionResult, resolve_identity
from src.policy import Decision


@dataclass
class SyntheticCaseResult:
    case_id: str
    decision: Decision
    reason_codes: list[str]
    identity_resolution: IdentityResolutionResult
    validation: CaseValidationReport
    fraud_assessment: FraudAssessment
    risk_assessment: RiskAssessment
    document_validations: list[DocumentValidationReport] = field(default_factory=list)


def run_synthetic_case(
    case_id: str,
    application: dict,
    documents: list[DocumentEvidence],
    raw_texts: dict[str, str] | None = None,
    legacy_decisions: dict[str, tuple[Decision, list[str]]] | None = None,
) -> SyntheticCaseResult:
    raw_texts = raw_texts or {d.document_id: "" for d in documents}
    legacy_decisions = legacy_decisions or {d.document_id: ("APPROVE", ["BASELINE_RULES_PASSED"]) for d in documents}

    validations = [validate_document(d) for d in documents]
    fraud_per_doc = [
        assess_document_fraud_signals(d.document_id, raw_texts.get(d.document_id, ""), d.evidence_reference, v)
        for d, v in zip(documents, validations)
    ]
    identity_resolution = resolve_identity(case_id, application, documents)
    case_validation = validate_case(case_id, validations, documents)
    fraud_assessment = assess_case_fraud(case_id, fraud_per_doc, identity_resolution, case_validation)

    summaries = [
        DocumentEvidenceSummary(
            document_id=d.document_id,
            legacy_decision=legacy_decisions.get(d.document_id, ("APPROVE", ["BASELINE_RULES_PASSED"]))[0],
            legacy_reason_codes=legacy_decisions.get(d.document_id, ("APPROVE", ["BASELINE_RULES_PASSED"]))[1],
            evidence=d, validation=v, fraud_signals=fs,
        )
        for d, v, fs in zip(documents, validations, fraud_per_doc)
    ]
    bundle = build_evidence_bundle(case_id, summaries, identity_resolution, case_validation, fraud_assessment)
    risk_assessment = assess_case_risk(bundle)

    legacy_reason_codes = sorted({r for _, codes in legacy_decisions.values() for r in codes})
    reason_codes = sorted(set(legacy_reason_codes) | set(risk_assessment.reason_codes))

    return SyntheticCaseResult(
        case_id=case_id,
        decision=risk_assessment.policy_outcome,
        reason_codes=reason_codes,
        identity_resolution=identity_resolution,
        validation=case_validation,
        fraud_assessment=fraud_assessment,
        risk_assessment=risk_assessment,
        document_validations=validations,
    )
