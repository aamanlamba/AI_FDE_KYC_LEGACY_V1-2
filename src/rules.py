from datetime import date

from .policy import MANDATORY_FIELDS, MIN_FIELD_COMPLETENESS_FOR_APPROVE, PATTERNS, TAMPER_MARKER

REFERENCE_DATE=date(2026,9,9)  # frozen for reproducible workshop results
MANDATORY=MANDATORY_FIELDS  # sourced from config/baseline.json when present (see src/policy.py)
# PATTERNS and TAMPER_MARKER moved to src/policy.py in stage P10 (they are shared
# domain constants, not decisioning-owned) -- re-exported here for backward
# compatibility with any existing `from .rules import PATTERNS` / `TAMPER_MARKER`.

def completeness(fields: dict) -> float:
    return round(sum(bool(fields.get(k)) for k in MANDATORY)/len(MANDATORY),3)

def evaluate(fields: dict, raw_text: str) -> tuple[str,list[str],list[str]]:
    reasons=[]; warnings=[]
    dtype=fields.get('document_type','').lower()
    c=completeness(fields)
    if c < MIN_FIELD_COMPLETENESS_FOR_APPROVE: reasons.append('INSUFFICIENT_MANDATORY_FIELDS')
    num=fields.get('document_number','')
    pat=PATTERNS.get(dtype)
    if pat and num and not pat.match(num): reasons.append('INVALID_DOCUMENT_NUMBER_FORMAT')
    expiry=fields.get('expiry_date')
    if expiry:
        try:
            if date.fromisoformat(expiry) < REFERENCE_DATE: reasons.append('DOCUMENT_EXPIRED')
        except ValueError: reasons.append('INVALID_EXPIRY_DATE')
    if TAMPER_MARKER in raw_text: reasons.append('SUSPECTED_TAMPERING')
    if 'DEGRADED' in raw_text: warnings.append('OCR_QUALITY_DEGRADED')
    if '90_DEGREES' in raw_text: warnings.append('ROTATED_DOCUMENT')
    if any(r in reasons for r in ('SUSPECTED_TAMPERING','DOCUMENT_EXPIRED')): return 'REJECT',reasons,warnings
    if reasons or warnings: return 'REVIEW',reasons or ['MANUAL_REVIEW_REQUIRED'],warnings
    return 'APPROVE',['BASELINE_RULES_PASSED'],warnings
