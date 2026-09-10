from datetime import date
import re

REFERENCE_DATE=date(2026,9,9)  # frozen for reproducible workshop results
MANDATORY=('full_name','date_of_birth','document_number','expiry_date')
PATTERNS={
'passport': re.compile(r'^PXT\d{6}$'),
'national_id': re.compile(r'^MID-\d{4}-\d{4}$'),
'driving_licence': re.compile(r'^MDL-\d{6}$'),
}

def completeness(fields: dict) -> float:
    return round(sum(bool(fields.get(k)) for k in MANDATORY)/len(MANDATORY),3)

def evaluate(fields: dict, raw_text: str) -> tuple[str,list[str],list[str]]:
    reasons=[]; warnings=[]
    dtype=fields.get('document_type','').lower()
    c=completeness(fields)
    if c < 0.75: reasons.append('INSUFFICIENT_MANDATORY_FIELDS')
    num=fields.get('document_number','')
    pat=PATTERNS.get(dtype)
    if pat and num and not pat.match(num): reasons.append('INVALID_DOCUMENT_NUMBER_FORMAT')
    expiry=fields.get('expiry_date')
    if expiry:
        try:
            if date.fromisoformat(expiry) < REFERENCE_DATE: reasons.append('DOCUMENT_EXPIRED')
        except ValueError: reasons.append('INVALID_EXPIRY_DATE')
    if 'ALTERED_TEXT_REGION_DETECTED' in raw_text: reasons.append('SUSPECTED_TAMPERING')
    if 'DEGRADED' in raw_text: warnings.append('OCR_QUALITY_DEGRADED')
    if '90_DEGREES' in raw_text: warnings.append('ROTATED_DOCUMENT')
    if any(r in reasons for r in ('SUSPECTED_TAMPERING','DOCUMENT_EXPIRED')): return 'REJECT',reasons,warnings
    if reasons or warnings: return 'REVIEW',reasons or ['MANUAL_REVIEW_REQUIRED'],warnings
    return 'APPROVE',['BASELINE_RULES_PASSED'],warnings
