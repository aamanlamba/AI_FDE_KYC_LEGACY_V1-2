from src.rules import evaluate, completeness

def test_clean_fields_approve():
    f={'document_type':'passport','full_name':'A','date_of_birth':'1990-01-01','document_number':'PXT123456','expiry_date':'2030-01-01'}
    d,r,w=evaluate(f,''); assert d=='APPROVE'; assert completeness(f)==1.0

def test_expired_rejects():
    f={'document_type':'passport','full_name':'A','date_of_birth':'1990-01-01','document_number':'PXT123456','expiry_date':'2025-01-01'}
    assert evaluate(f,'')[0]=='REJECT'

def test_tamper_rejects():
    f={'document_type':'passport','full_name':'A','date_of_birth':'1990-01-01','document_number':'PXT123456','expiry_date':'2030-01-01'}
    assert evaluate(f,'SECURITY NOTE: ALTERED_TEXT_REGION_DETECTED')[0]=='REJECT'
