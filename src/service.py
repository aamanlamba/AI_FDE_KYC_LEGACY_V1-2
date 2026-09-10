from .ocr import extract_text
from .parser import parse_legacy_ocr
from .rules import evaluate, completeness
from .repository import load_application
from .models import DocumentResult, CaseResult
from .document_intelligence import extract_evidence, get_default_provider
from .identity_resolution import resolve_identity
from .evidence_validation import validate_document as validate_document_evidence, validate_case as validate_case_evidence
from .fraud_signals import assess_document_fraud_signals, assess_case_fraud
from .decision_policy import DocumentEvidenceSummary, build_evidence_bundle, assess_case_risk

def verify_document(document_id: str) -> DocumentResult:
    text=extract_text(document_id)
    fields,parse_warnings=parse_legacy_ocr(text)
    decision,reasons,rule_warnings=evaluate(fields,text)
    evidence=extract_evidence(get_default_provider(),document_id)
    validation=validate_document_evidence(evidence)
    fraud_signals=assess_document_fraud_signals(document_id,text,evidence.evidence_reference,validation)
    return DocumentResult(document_id=document_id,document_type=fields.get('document_type'),decision=decision,
        reason_codes=reasons,parsed_fields=fields,completeness=completeness(fields),warnings=parse_warnings+rule_warnings,
        evidence=evidence,validation=validation,fraud_signals=fraud_signals)

def verify_case(case_id: str) -> CaseResult:
    app=load_application(case_id)
    docs=[verify_document(x) for x in app['document_ids']]
    legacy_reason_codes=sorted({r for d in docs for r in d.reason_codes})
    identity_resolution=resolve_identity(case_id,app,[d.evidence for d in docs])
    validation=validate_case_evidence(case_id,[d.validation for d in docs],[d.evidence for d in docs])
    fraud_assessment=assess_case_fraud(case_id,[d.fraud_signals for d in docs],identity_resolution,validation)
    document_summaries=[DocumentEvidenceSummary(document_id=d.document_id,legacy_decision=d.decision,
        legacy_reason_codes=d.reason_codes,evidence=d.evidence,validation=d.validation,
        fraud_signals=d.fraud_signals) for d in docs]
    bundle=build_evidence_bundle(case_id,document_summaries,identity_resolution,validation,fraud_assessment)
    risk_assessment=assess_case_risk(bundle)
    reason_codes=sorted(set(legacy_reason_codes)|set(risk_assessment.reason_codes))
    return CaseResult(case_id=case_id,decision=risk_assessment.policy_outcome,reason_codes=reason_codes,documents=docs,
      limitation_notice='Repo 1.0.2 case decisions are computed by an explicit, deterministic decision policy '
        '(src/decision_policy/, policy_version in risk_assessment.policy_version) over evidence, identity '
        'resolution, validation and fraud signals -- no longer a worst-of-documents aggregation. See '
        'risk_assessment.risk_factors/explanation for the full, inspectable basis of this decision.',
      identity_resolution=identity_resolution,validation=validation,fraud_assessment=fraud_assessment,
      risk_assessment=risk_assessment)
