PREFIXES={
'DOCUMENT TYPE:':'document_type','NAME:':'full_name','DOB:':'date_of_birth',
'DOCUMENT NO:':'document_number','ISSUE DATE:':'issue_date','EXPIRY DATE:':'expiry_date',
'ADDRESS:':'address','NATIONALITY:':'nationality'
}

def parse_legacy_ocr(text: str) -> tuple[dict,list[str]]:
    fields={}; warnings=[]
    for raw in text.splitlines():
        line=raw.strip()
        matched=False
        for prefix,key in PREFIXES.items():
            if line.startswith(prefix):
                fields[key]=line[len(prefix):].strip(); matched=True; break
        if not matched and ':' in line and not line.startswith(('OCR_QUALITY:','UNREADABLE_GLYPHS:','CAPTURE_ORIENTATION:','SECURITY NOTE:')):
            warnings.append(f'UNPARSED_LINE:{line[:40]}')
    if 'OCR_QUALITY: DEGRADED' in text: warnings.append('DEGRADED_OCR_QUALITY')
    if 'CAPTURE_ORIENTATION: 90_DEGREES' in text: warnings.append('ROTATED_CAPTURE')
    return fields,warnings
