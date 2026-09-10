from .ocr import extract_text
from .parser import parse_legacy_ocr
from .rules import evaluate, completeness
from .repository import load_application
from .models import DocumentResult, CaseResult

RANK={'APPROVE':0,'REVIEW':1,'REJECT':2}

def verify_document(document_id: str) -> DocumentResult:
    text=extract_text(document_id)
    fields,parse_warnings=parse_legacy_ocr(text)
    decision,reasons,rule_warnings=evaluate(fields,text)
    return DocumentResult(document_id=document_id,document_type=fields.get('document_type'),decision=decision,
        reason_codes=reasons,parsed_fields=fields,completeness=completeness(fields),warnings=parse_warnings+rule_warnings)

def verify_case(case_id: str) -> CaseResult:
    app=load_application(case_id)
    docs=[verify_document(x) for x in app['document_ids']]
    worst=max(docs,key=lambda x:RANK[x.decision]).decision
    reason_codes=sorted({r for d in docs for r in d.reason_codes})
    return CaseResult(case_id=case_id,decision=worst,reason_codes=reason_codes,documents=docs,
      limitation_notice='Repo 1.0 aggregates document decisions only; it does not perform robust cross-document identity resolution.')
