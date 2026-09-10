from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def test_health_live():
    r = client.get('/health/live')
    assert r.status_code == 200
    assert r.json() == {'status': 'ok'}


def test_health_ready():
    r = client.get('/health/ready')
    assert r.status_code == 200
    assert r.json()['dataset_cases'] == 6
    assert r.json()['offline_ocr'] is True


def test_cases():
    r = client.get('/v1/cases')
    assert r.status_code == 200
    assert len(r.json()) == 6


def test_verify_document():
    r = client.post('/v1/documents/verify', json={'document_id': 'CASE-001-PASSPORT'})
    assert r.status_code == 200
    assert r.json()['decision'] == 'APPROVE'


def test_verify_case():
    r = client.post('/v1/cases/CASE-004/verify')
    assert r.status_code == 200
    assert r.json()['decision'] == 'REJECT'


def test_unknown_document_404():
    assert client.post('/v1/documents/verify', json={'document_id': 'CASE-999-X'}).status_code == 404


def test_unknown_case_404():
    assert client.post('/v1/cases/CASE-999/verify').status_code == 404


def test_path_traversal_blocked():
    assert client.post('/v1/documents/verify', json={'document_id': '../secret'}).status_code == 400


def test_request_validation_rejects_empty_document_id():
    assert client.post('/v1/documents/verify', json={'document_id': ''}).status_code == 422


def test_correlation_id_is_preserved():
    r = client.get('/health/live', headers={'x-correlation-id': 'workshop-test-123'})
    assert r.headers['x-correlation-id'] == 'workshop-test-123'
