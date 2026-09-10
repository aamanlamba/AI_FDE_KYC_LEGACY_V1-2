from src.service import verify_document, verify_case

def test_clean_case_approves(): assert verify_case('CASE-001').decision=='APPROVE'
def test_noisy_case_reviews(): assert verify_case('CASE-002').decision=='REVIEW'
def test_rotated_case_reviews(): assert verify_case('CASE-003').decision=='REVIEW'
def test_expired_case_rejects():
    r=verify_case('CASE-004'); assert r.decision=='REJECT'; assert 'DOCUMENT_EXPIRED' in r.reason_codes
def test_name_variation_now_triggers_review():
    # P0-P4 left this at APPROVE (the documented brownfield gap: no cross-document
    # name reconciliation). As of P5's decision policy, the identity conflict is a
    # risk factor and the case escalates to REVIEW -- it is no longer silently approved.
    r=verify_case('CASE-005'); assert r.decision=='REVIEW'; assert r.risk_assessment.identity_conflict_count >= 1
def test_tamper_case_rejects():
    r=verify_case('CASE-006'); assert r.decision=='REJECT'; assert 'SUSPECTED_TAMPERING' in r.reason_codes
def test_ocr_corruption_is_preserved():
    r=verify_document('CASE-005-NID'); assert 'Moharnmad' in r.parsed_fields['full_name']
