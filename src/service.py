from .ocr import extract_text
from .parser import parse_legacy_ocr
from .rules import evaluate, completeness
from .repository import load_application
from .models import DocumentResult, CaseResult
from .document_intelligence import extract_evidence, get_default_provider
from .identity_resolution import resolve_identity
from .evidence_validation import validate_document as validate_document_evidence, validate_case as validate_case_evidence

RANK={'APPROVE':0,'REVIEW':1,'REJECT':2}

def verify_document(document_id: str) -> DocumentResult:
    text=extract_text(document_id)
    fields,parse_warnings=parse_legacy_ocr(text)
    decision,reasons,rule_warnings=evaluate(fields,text)
    evidence=extract_evidence(get_default_provider(),document_id)
    validation=validate_document_evidence(evidence)
    return DocumentResult(document_id=document_id,document_type=fields.get('document_type'),decision=decision,
        reason_codes=reasons,parsed_fields=fields,completeness=completeness(fields),warnings=parse_warnings+rule_warnings,
        evidence=evidence,validation=validation)

def verify_case(case_id: str) -> CaseResult:
    app=load_application(case_id)
    docs=[verify_document(x) for x in app['document_ids']]
    worst=max(docs,key=lambda x:RANK[x.decision]).decision
    reason_codes=sorted({r for d in docs for r in d.reason_codes})
    identity_resolution=resolve_identity(case_id,app,[d.evidence for d in docs])
    validation=validate_case_evidence(case_id,[d.validation for d in docs],[d.evidence for d in docs])
    return CaseResult(case_id=case_id,decision=worst,reason_codes=reason_codes,documents=docs,
      limitation_notice='Repo 1.0 case decisions still aggregate document-level decisions only (worst-of); '
        'identity_resolution and validation are now computed and reported (see identity_resolution.overall_status/confidence '
        'and validation.document_reports/case_level_results) but neither is yet consulted by the decision policy.',
      identity_resolution=identity_resolution,validation=validation)
