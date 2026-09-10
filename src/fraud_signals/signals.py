from ..evidence_validation import CaseValidationReport, DocumentValidationReport, ValidationStatus
from ..evidence_validation.models import Severity
from ..identity_resolution import IdentityResolutionResult, MatchStatus
from .models import FraudCategory, FraudSignal

# Only genuinely impossible/abnormal temporal relationships count as fraud-relevant
# anomalies. Plain expiry (EXPIRY-NOT-PAST FAIL) is deliberately excluded: an expired
# document is a mundane lifecycle event handled by src/rules.py's own decision path,
# not a suspicious anomaly.
_TEMPORAL_ANOMALY_RULE_IDS = {"TEMPORAL-ISSUE-NOT-FUTURE", "ISSUEDATE-BEFORE-EXPIRY", "DOB-BEFORE-ISSUE"}

_FIELD_INCONSISTENCY_RULE_IDS = {"SCHEMA-001"}
_EXTRACTION_INCONSISTENCY_RULE_IDS = {"DOCNUM-FORMAT"}


def derive_temporal_anomaly_signals(report: DocumentValidationReport) -> list[FraudSignal]:
    """Only actual FAILs become signals — NOT_APPLICABLE/UNKNOWN (missing or unreadable
    evidence) never fabricates a fraud signal (requirement: missing fraud evidence)."""
    signals = []
    for result in report.results:
        if result.rule_id in _TEMPORAL_ANOMALY_RULE_IDS and result.status == ValidationStatus.FAIL:
            signals.append(FraudSignal(
                signal_id=f"{report.document_id}:{result.rule_id}",
                category=FraudCategory.TEMPORAL_ANOMALY,
                severity=Severity.HIGH,
                confidence=None,
                source=f"evidence_validation:{result.rule_id}",
                supporting_evidence=result.evidence_references,
                explanation=f"An impossible/abnormal temporal relationship was found: {result.explanation}",
            ))
    return signals


def derive_extraction_inconsistency_signals(report: DocumentValidationReport) -> list[FraudSignal]:
    signals = []
    for result in report.results:
        if result.status != ValidationStatus.FAIL:
            continue
        if result.rule_id in _FIELD_INCONSISTENCY_RULE_IDS:
            category = FraudCategory.FIELD_INCONSISTENCY
        elif result.rule_id in _EXTRACTION_INCONSISTENCY_RULE_IDS:
            category = FraudCategory.EXTRACTION_INCONSISTENCY
        else:
            continue
        signals.append(FraudSignal(
            signal_id=f"{report.document_id}:{result.rule_id}",
            category=category,
            severity=Severity.MEDIUM,
            confidence=None,
            source=f"evidence_validation:{result.rule_id}",
            supporting_evidence=result.evidence_references,
            explanation=f"A suspicious extraction/field inconsistency was found: {result.explanation}",
        ))
    return signals


def derive_identity_conflict_signals(result: IdentityResolutionResult) -> list[FraudSignal]:
    signals = []
    for attribute_comparison in result.attribute_comparisons:
        for pair in attribute_comparison.pairwise:
            if pair.status != MatchStatus.CONFLICT:
                continue
            similarity = pair.similarity if pair.similarity is not None else 0.0
            confidence = round(1 - similarity, 3)
            severity = Severity.HIGH if attribute_comparison.attribute == "date_of_birth" else Severity.MEDIUM
            signals.append(FraudSignal(
                signal_id=f"{result.case_id}:{attribute_comparison.attribute}:{pair.source_a}:{pair.source_b}",
                category=FraudCategory.IDENTITY_CONFLICT,
                severity=severity,
                confidence=confidence,
                source=f"identity_resolution:{attribute_comparison.attribute}",
                supporting_evidence=[pair.source_a, pair.source_b],
                explanation=f"Conflicting {attribute_comparison.attribute} between {pair.source_a} and "
                    f"{pair.source_b} ({'; '.join(pair.notes)}).",
            ))
    return signals


def derive_document_duplication_signals(report: CaseValidationReport) -> list[FraudSignal]:
    signals = []
    for result in report.case_level_results:
        if result.rule_id == "CROSSDOC-NO-DUPLICATE-TYPE" and result.status == ValidationStatus.FAIL:
            signals.append(FraudSignal(
                signal_id=f"{report.case_id}:{result.rule_id}",
                category=FraudCategory.DOCUMENT_DUPLICATION,
                severity=Severity.MEDIUM,
                confidence=None,
                source=f"evidence_validation:{result.rule_id}",
                supporting_evidence=result.evidence_references,
                explanation=f"Unusual document duplication was found: {result.explanation}",
            ))
    return signals
