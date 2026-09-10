from ..evidence_validation.models import Severity, ValidationStatus
from ..identity_resolution import MatchStatus
from .models import DocumentEvidenceSummary, EvidenceBundle, RiskFactor, RiskFactorCategory


def _document_risk_factors(documents: list[DocumentEvidenceSummary]) -> list[RiskFactor]:
    factors: list[RiskFactor] = []
    for doc in documents:
        if doc.legacy_decision == "REJECT":
            factors.append(RiskFactor(
                factor_id=f"{doc.document_id}:DOCUMENT_REJECT",
                category=RiskFactorCategory.DOCUMENT_DECISION,
                severity=Severity.CRITICAL,
                triggers_hard_stop=True,
                description=f"{doc.document_id} independently REJECTed by document-level rules: "
                    f"{', '.join(doc.legacy_reason_codes) or 'no reason codes'}.",
                source="rules.evaluate",
                evidence_references=[doc.evidence.evidence_reference],
            ))
        elif doc.legacy_decision == "REVIEW":
            factors.append(RiskFactor(
                factor_id=f"{doc.document_id}:DOCUMENT_REVIEW",
                category=RiskFactorCategory.DOCUMENT_DECISION,
                severity=Severity.MEDIUM,
                triggers_hard_stop=False,
                description=f"{doc.document_id} independently flagged for REVIEW by document-level rules: "
                    f"{', '.join(doc.legacy_reason_codes) or 'no reason codes'}.",
                source="rules.evaluate",
                evidence_references=[doc.evidence.evidence_reference],
            ))

        if doc.evidence.quality.value == "incomplete_unreadable":
            factors.append(RiskFactor(
                factor_id=f"{doc.document_id}:EVIDENCE_UNREADABLE",
                category=RiskFactorCategory.EVIDENCE_QUALITY,
                severity=Severity.MEDIUM,
                triggers_hard_stop=False,
                description=f"{doc.document_id} evidence quality is incomplete/unreadable.",
                source="document_intelligence.quality",
                evidence_references=[doc.evidence.evidence_reference],
            ))

        for result in doc.validation.results:
            if result.status == ValidationStatus.UNKNOWN:
                factors.append(RiskFactor(
                    factor_id=f"{doc.document_id}:{result.rule_id}:UNKNOWN",
                    category=RiskFactorCategory.EVIDENCE_QUALITY,
                    severity=Severity.MEDIUM,
                    triggers_hard_stop=False,
                    description=f"{doc.document_id}: {result.explanation}",
                    source=f"evidence_validation:{result.rule_id}",
                    evidence_references=result.evidence_references,
                ))
            elif result.status == ValidationStatus.FAIL:
                factors.append(RiskFactor(
                    factor_id=f"{doc.document_id}:{result.rule_id}:FAIL",
                    category=RiskFactorCategory.VALIDATION_FAILURE,
                    severity=result.severity,
                    triggers_hard_stop=(result.severity == Severity.CRITICAL),
                    description=f"{doc.document_id}: {result.explanation}",
                    source=f"evidence_validation:{result.rule_id}",
                    evidence_references=result.evidence_references,
                ))
    return factors


def _identity_risk_factors(identity_resolution) -> list[RiskFactor]:
    factors: list[RiskFactor] = []
    for attribute_comparison in identity_resolution.attribute_comparisons:
        if attribute_comparison.status == MatchStatus.CONFLICT:
            # A contradictory DOB is exact-or-contradiction (never ambiguous, see
            # src/identity_resolution/matching.py:compare_dob) -- the strongest,
            # least ambiguous identity-evidence hard-stop available. A conflicting
            # name/address alone is treated as review-worthy, not an automatic
            # rejection, since spelling/transliteration variance can plausibly
            # produce a below-threshold similarity without being fraudulent.
            is_dob = attribute_comparison.attribute == "date_of_birth"
            factors.append(RiskFactor(
                factor_id=f"{identity_resolution.case_id}:{attribute_comparison.attribute}:CONFLICT",
                category=RiskFactorCategory.IDENTITY_CONFLICT,
                severity=Severity.CRITICAL if is_dob else Severity.HIGH,
                triggers_hard_stop=is_dob,
                description=f"Identity attribute '{attribute_comparison.attribute}' conflicts across "
                    f"evidence sources for this case.",
                source="identity_resolution",
                evidence_references=attribute_comparison.supporting_documents,
            ))
        elif attribute_comparison.status == MatchStatus.FUZZY_MATCH:
            factors.append(RiskFactor(
                factor_id=f"{identity_resolution.case_id}:{attribute_comparison.attribute}:FUZZY",
                category=RiskFactorCategory.IDENTITY_UNCERTAINTY,
                severity=Severity.MEDIUM,
                triggers_hard_stop=False,
                description=f"Identity attribute '{attribute_comparison.attribute}' matches only "
                    f"approximately across evidence sources (fuzzy match; not proof of identity).",
                source="identity_resolution",
                evidence_references=attribute_comparison.supporting_documents,
            ))
        elif attribute_comparison.status == MatchStatus.INSUFFICIENT_EVIDENCE:
            factors.append(RiskFactor(
                factor_id=f"{identity_resolution.case_id}:{attribute_comparison.attribute}:INSUFFICIENT",
                category=RiskFactorCategory.IDENTITY_UNCERTAINTY,
                severity=Severity.LOW,
                triggers_hard_stop=False,
                description=f"Insufficient evidence to compare identity attribute "
                    f"'{attribute_comparison.attribute}' across sources.",
                source="identity_resolution",
                evidence_references=attribute_comparison.supporting_documents,
            ))
    return factors


def _fraud_risk_factors(fraud_assessment) -> list[RiskFactor]:
    all_signals = [s for ds in fraud_assessment.document_signals for s in ds.signals]
    all_signals += fraud_assessment.case_level_signals
    return [
        RiskFactor(
            factor_id=f"FRAUD:{signal.signal_id}",
            category=RiskFactorCategory.FRAUD_SIGNAL,
            severity=signal.severity,
            triggers_hard_stop=(signal.severity == Severity.CRITICAL),
            description=signal.explanation,
            source=signal.source,
            evidence_references=signal.supporting_evidence,
        )
        for signal in all_signals
    ]


def _case_validation_risk_factors(case_validation) -> list[RiskFactor]:
    factors: list[RiskFactor] = []
    for result in case_validation.case_level_results:
        if result.status == ValidationStatus.FAIL:
            factors.append(RiskFactor(
                factor_id=f"CASE:{result.rule_id}",
                category=RiskFactorCategory.VALIDATION_FAILURE,
                severity=result.severity,
                triggers_hard_stop=(result.severity == Severity.CRITICAL),
                description=result.explanation,
                source=f"evidence_validation:{result.rule_id}",
                evidence_references=result.evidence_references,
            ))
    return factors


def derive_risk_factors(bundle: EvidenceBundle) -> list[RiskFactor]:
    return [
        *_document_risk_factors(bundle.documents),
        *_identity_risk_factors(bundle.identity_resolution),
        *_fraud_risk_factors(bundle.fraud_assessment),
        *_case_validation_risk_factors(bundle.case_validation),
    ]
