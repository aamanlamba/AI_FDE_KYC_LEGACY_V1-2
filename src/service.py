from .ocr import extract_text
from .parser import parse_legacy_ocr
from .rules import evaluate, completeness
from .repository import load_application
from .models import DocumentResult, CaseResult
from .document_intelligence import extract_evidence, get_default_provider
from .identity_resolution import resolve_identity, MatchStatus
from .evidence_validation import validate_document as validate_document_evidence, validate_case as validate_case_evidence, ValidationStatus
from .fraud_signals import assess_document_fraud_signals, assess_case_fraud, FraudAssessmentStatus
from .decision_policy import DocumentEvidenceSummary, build_evidence_bundle, assess_case_risk
from .observability import get_current_trace_context, start_span, build_decision_lineage
from .observability import metrics as obs_metrics

def verify_document(document_id: str) -> DocumentResult:
    with start_span('service.verify_document', document_id=document_id):
        text=extract_text(document_id)
        fields,parse_warnings=parse_legacy_ocr(text)
        decision,reasons,rule_warnings=evaluate(fields,text)

        try:
            with start_span('document_intelligence.extract', document_id=document_id):
                evidence=extract_evidence(get_default_provider(),document_id)
        except Exception:
            obs_metrics.provider_failures.inc(provider='document_intelligence')
            raise
        obs_metrics.document_types_seen.inc(document_type=evidence.document_type.value)
        if any(f.value is None for f in evidence.fields.values()):
            obs_metrics.extraction_failures.inc(document_type=evidence.document_type.value)

        with start_span('evidence_validation.validate_document', document_id=document_id):
            validation=validate_document_evidence(evidence)
        for result in validation.results:
            if result.status==ValidationStatus.FAIL:
                obs_metrics.validation_failures.inc(rule_id=result.rule_id)

        with start_span('fraud_signals.assess_document', document_id=document_id):
            fraud_signals=assess_document_fraud_signals(document_id,text,evidence.evidence_reference,validation)

        return DocumentResult(document_id=document_id,document_type=fields.get('document_type'),decision=decision,
            reason_codes=reasons,parsed_fields=fields,completeness=completeness(fields),warnings=parse_warnings+rule_warnings,
            evidence=evidence,validation=validation,fraud_signals=fraud_signals)

def verify_case(case_id: str) -> CaseResult:
    with start_span('service.verify_case', case_id=case_id):
        app=load_application(case_id)
        docs=[verify_document(x) for x in app['document_ids']]
        legacy_reason_codes=sorted({r for d in docs for r in d.reason_codes})

        with start_span('identity_resolution.resolve', case_id=case_id):
            identity_resolution=resolve_identity(case_id,app,[d.evidence for d in docs])
        for attribute_comparison in identity_resolution.attribute_comparisons:
            if attribute_comparison.status==MatchStatus.CONFLICT:
                obs_metrics.identity_conflicts.inc(attribute=attribute_comparison.attribute)

        with start_span('evidence_validation.validate_case', case_id=case_id):
            validation=validate_case_evidence(case_id,[d.validation for d in docs],[d.evidence for d in docs])
        for result in validation.case_level_results:
            if result.status==ValidationStatus.FAIL:
                obs_metrics.validation_failures.inc(rule_id=result.rule_id)

        with start_span('fraud_signals.assess_case', case_id=case_id):
            fraud_assessment=assess_case_fraud(case_id,[d.fraud_signals for d in docs],identity_resolution,validation)
        if fraud_assessment.status!=FraudAssessmentStatus.NO_SIGNALS_DETECTED:
            top_category=fraud_assessment.case_level_signals[0].category.value if fraud_assessment.case_level_signals else (
                fraud_assessment.document_signals[0].signals[0].category.value if fraud_assessment.document_signals and fraud_assessment.document_signals[0].signals else 'unknown')
            obs_metrics.fraud_referrals.inc(category=top_category)

        document_summaries=[DocumentEvidenceSummary(document_id=d.document_id,legacy_decision=d.decision,
            legacy_reason_codes=d.reason_codes,evidence=d.evidence,validation=d.validation,
            fraud_signals=d.fraud_signals) for d in docs]
        bundle=build_evidence_bundle(case_id,document_summaries,identity_resolution,validation,fraud_assessment)

        with start_span('decision_policy.assess', case_id=case_id):
            risk_assessment=assess_case_risk(bundle)
        reason_codes=sorted(set(legacy_reason_codes)|set(risk_assessment.reason_codes))
        obs_metrics.decisions_total.inc(decision=risk_assessment.policy_outcome)

        decision_lineage=build_decision_lineage(case_id,risk_assessment.policy_outcome,risk_assessment,get_current_trace_context())

        return CaseResult(case_id=case_id,decision=risk_assessment.policy_outcome,reason_codes=reason_codes,documents=docs,
          limitation_notice='Repo 1.0.2 case decisions are computed by an explicit, deterministic decision policy '
            '(src/decision_policy/, policy_version in risk_assessment.policy_version) over evidence, identity '
            'resolution, validation and fraud signals -- no longer a worst-of-documents aggregation. See '
            'risk_assessment.risk_factors/explanation for the full, inspectable basis of this decision.',
          identity_resolution=identity_resolution,validation=validation,fraud_assessment=fraud_assessment,
          risk_assessment=risk_assessment,decision_lineage=decision_lineage)
