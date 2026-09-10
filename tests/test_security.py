import logging

import pytest
from fastapi.testclient import TestClient

import src.app as appmod
from src.repository import safe_id
from src.review import ReviewStatus, ReviewStore, open_review_case
from src.security import (
    AuthenticationError,
    AuthorizationError,
    RateLimitExceededError,
    RateLimiter,
    StaticWorkshopAuthorizer,
    authorize,
    log_operational_event,
    mask_tail,
    redact_partial,
    sanitize_for_display,
    validate_identifier,
)
from src.service import verify_case

REVIEWER_HEADERS = {"X-API-Key": "workshop-reviewer-key"}


@pytest.fixture
def store():
    return ReviewStore(":memory:")


@pytest.fixture
def client(store):
    appmod.app.dependency_overrides[appmod.review_store_dependency] = lambda: store
    try:
        yield TestClient(appmod.app)
    finally:
        appmod.app.dependency_overrides.clear()


# --- path traversal / malformed identifiers (allowlist, not denylist) --------------

@pytest.mark.parametrize("bad_id", [
    "../secret", "..\\secret", "/etc/passwd", "C:\\Windows\\System32",
    "CASE-001\x00.json", "CASE-001\n\rINJECTED", "café-001", "🙂-001",
    "", "-leading-hyphen", "1starts-with-digit", "a" * 200,
])
def test_identifier_allowlist_rejects_every_malformed_id(bad_id):
    with pytest.raises(ValueError):
        safe_id(bad_id)


def test_identifier_allowlist_accepts_every_real_dataset_id():
    for good_id in ("CASE-001", "CASE-001-PASSPORT", "CASE-005-NID"):
        assert safe_id(good_id) == good_id


def test_api_rejects_path_traversal_in_document_id(client):
    r = client.post("/v1/documents/verify", json={"document_id": "../secret"})
    assert r.status_code == 400


def test_api_rejects_oversized_case_id_path_param_before_touching_the_filesystem(client):
    r = client.post(f"/v1/cases/{'A' * 500}/verify")
    assert r.status_code == 422  # rejected by the path pattern, never reaches repository.py


def test_api_rejects_malformed_case_id_path_param(client):
    r = client.post("/v1/cases/../../etc/passwd/verify")
    # Starlette normalizes '..' segments in the URL itself; either way this must
    # never resolve to a 200 with unintended file content.
    assert r.status_code in (404, 422)


# --- resource bounds ------------------------------------------------------------------

def test_oversized_rationale_is_rejected(client):
    r = client.post("/v1/cases/CASE-005/reviews", headers=REVIEWER_HEADERS)
    review_id = r.json()["review_id"]
    r2 = client.post(
        f"/v1/reviews/{review_id}/transitions",
        headers=REVIEWER_HEADERS,
        json={"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "x" * 5000},
    )
    assert r2.status_code == 422


def test_repository_refuses_to_read_a_file_beyond_the_size_bound(tmp_path, monkeypatch):
    from src import repository

    oversized = tmp_path / "HUGE.txt"
    oversized.write_text("x" * (repository.MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError):
        repository._read_bounded(oversized)


# --- schema bypass (extra fields rejected) ------------------------------------------

def test_unexpected_extra_field_in_document_verify_request_is_rejected(client):
    r = client.post("/v1/documents/verify", json={"document_id": "CASE-001-PASSPORT", "admin": True})
    assert r.status_code == 422


def test_unexpected_extra_field_in_transition_request_is_rejected(client):
    r = client.post("/v1/cases/CASE-005/reviews", headers=REVIEWER_HEADERS)
    review_id = r.json()["review_id"]
    r2 = client.post(
        f"/v1/reviews/{review_id}/transitions",
        headers=REVIEWER_HEADERS,
        json={"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "ok", "role": "admin"},
    )
    assert r2.status_code == 422


# --- authentication / authorization on review endpoints -----------------------------

def test_open_review_without_credential_is_rejected(client):
    r = client.post("/v1/cases/CASE-005/reviews")
    assert r.status_code == 401


def test_open_review_with_wrong_credential_is_rejected(client):
    r = client.post("/v1/cases/CASE-005/reviews", headers={"X-API-Key": "not-a-real-key"})
    assert r.status_code == 401


def test_list_reviews_without_credential_is_rejected(client):
    assert client.get("/v1/reviews").status_code == 401


def test_get_review_without_credential_is_rejected(client):
    assert client.get("/v1/reviews/RVW-ANYTHING").status_code == 401


def test_review_history_without_credential_is_rejected(client):
    assert client.get("/v1/reviews/RVW-ANYTHING/history").status_code == 401


def test_transition_without_credential_is_rejected(client):
    r = client.post(
        "/v1/reviews/RVW-ANYTHING/transitions",
        json={"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "n/a"},
    )
    assert r.status_code == 401


def test_review_endpoints_succeed_with_the_correct_credential(client):
    opened = client.post("/v1/cases/CASE-005/reviews", headers=REVIEWER_HEADERS)
    assert opened.status_code == 201
    review_id = opened.json()["review_id"]
    assert client.get("/v1/reviews", headers=REVIEWER_HEADERS).status_code == 200
    assert client.get(f"/v1/reviews/{review_id}", headers=REVIEWER_HEADERS).status_code == 200
    assert client.get(f"/v1/reviews/{review_id}/history", headers=REVIEWER_HEADERS).status_code == 200


def test_legacy_verify_endpoints_remain_unauthenticated(client):
    # documented, deliberate scope boundary -- see docs/security/threat_model.md
    assert client.post("/v1/documents/verify", json={"document_id": "CASE-001-PASSPORT"}).status_code == 200
    assert client.post("/v1/cases/CASE-001/verify").status_code == 200


def test_authorize_helper_distinguishes_authentication_from_authorization():
    authorizer = StaticWorkshopAuthorizer(credentials={"valid-key": frozenset({"reviewer"})})
    with pytest.raises(AuthenticationError):
        authorize(None, "reviewer", authorizer)
    with pytest.raises(AuthenticationError):
        authorize("wrong-key", "reviewer", authorizer)
    with pytest.raises(AuthorizationError):
        authorize("valid-key", "admin", authorizer)  # valid credential, wrong role
    principal = authorize("valid-key", "reviewer", authorizer)
    assert principal.subject and "reviewer" in principal.roles


# --- rate limiting -----------------------------------------------------------------

def test_rate_limiter_blocks_after_the_configured_threshold():
    limiter = RateLimiter(max_requests=3, window_seconds=60.0)
    for _ in range(3):
        limiter.check("subject-a")
    with pytest.raises(RateLimitExceededError):
        limiter.check("subject-a")


def test_rate_limiter_tracks_subjects_independently():
    limiter = RateLimiter(max_requests=1, window_seconds=60.0)
    limiter.check("subject-a")
    limiter.check("subject-b")  # a different subject is not affected by subject-a's usage
    with pytest.raises(RateLimitExceededError):
        limiter.check("subject-a")


def test_api_rate_limits_review_transitions(client):
    import src.security.limits as limits_mod

    limits_mod.review_transition_rate_limiter.reset()
    opened = client.post("/v1/cases/CASE-005/reviews", headers=REVIEWER_HEADERS)
    review_id = opened.json()["review_id"]
    body = {"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "ok"}
    for _ in range(limits_mod.review_transition_rate_limiter._max_requests):
        client.post(f"/v1/reviews/{review_id}/transitions", headers=REVIEWER_HEADERS, json=body)
    r = client.post(f"/v1/reviews/{review_id}/transitions", headers=REVIEWER_HEADERS, json=body)
    assert r.status_code == 429
    limits_mod.review_transition_rate_limiter.reset()


# --- SQL-injection-safe persistence --------------------------------------------------

def test_review_store_is_safe_against_sql_metacharacters_in_free_text_fields(store):
    review = open_review_case(verify_case("CASE-005"), store)
    malicious = "'); DROP TABLE review_cases; --"
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, malicious, malicious, correction=malicious)
    # the table must still exist and contain exactly the rows we expect
    reloaded = store.get_review(review.review_id)
    assert reloaded is not None
    assert reloaded.status == ReviewStatus.IN_REVIEW
    log = store.get_audit_log(review.review_id)
    assert len(log) == 1
    assert log[0].analyst_action == malicious  # stored verbatim as data, not executed as SQL
    assert log[0].correction == malicious


# --- centralized secure error handling ------------------------------------------------

def test_unhandled_exception_returns_generic_message_not_internal_detail(monkeypatch):
    def boom(case_id):
        raise RuntimeError("super secret internal stack detail: /etc/shadow contents")

    monkeypatch.setattr(appmod, "verify_case", boom)
    # raise_server_exceptions=False: exercise the real HTTP response the centralized
    # handler produces, rather than TestClient re-raising the exception into the test.
    unraising_client = TestClient(appmod.app, raise_server_exceptions=False)
    r = unraising_client.post("/v1/cases/CASE-001/verify")
    assert r.status_code == 500
    assert "internal error" == r.json()["detail"]
    assert "secret" not in r.text and "/etc/shadow" not in r.text
    assert "correlation_id" in r.json()


def test_unhandled_exception_response_still_carries_a_correlation_id(monkeypatch):
    def boom(case_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(appmod, "verify_case", boom)
    unraising_client = TestClient(appmod.app, raise_server_exceptions=False)
    r = unraising_client.post("/v1/cases/CASE-001/verify", headers={"x-correlation-id": "test-cid-123"})
    assert r.status_code == 500
    assert r.json()["correlation_id"] == "test-cid-123"


# --- PII minimization in logs ---------------------------------------------------------

def test_request_logging_never_includes_identity_attribute_values(client, caplog):
    with caplog.at_level(logging.INFO, logger="kyc-v1"):
        client.post("/v1/documents/verify", json={"document_id": "CASE-001-PASSPORT"})
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    # The correlation-id access log must contain operational identifiers only.
    assert "CASE-001-PASSPORT" not in log_text  # not logged in the path (it's in the body)
    for pii_value in ("Aarav Mehta", "PXT100184", "1991-04-12"):
        assert pii_value not in log_text


def test_log_operational_event_rejects_unknown_field_names():
    logger = logging.getLogger("test-secure-logging")
    with pytest.raises(ValueError):
        log_operational_event(logger, "test_event", full_name="Aarav Mehta")  # not an allowed field


def test_log_operational_event_accepts_allowed_fields(caplog):
    logger = logging.getLogger("test-secure-logging-2")
    with caplog.at_level(logging.INFO, logger="test-secure-logging-2"):
        log_operational_event(logger, "case_reviewed", case_id="CASE-005", decision="REVIEW")
    assert any("case_id='CASE-005'" in r.getMessage() for r in caplog.records)


# --- document content is DATA: sanitization / injection resistance -------------------

def test_sanitize_for_display_strips_control_characters_and_newlines():
    hostile = "Normal Name\n2026-01-01 FAKE_LOG_LINE injected=true\x00\x1b[31m"
    result = sanitize_for_display(hostile)
    assert "\n" not in result and "\x00" not in result and "\x1b" not in result
    assert "Normal Name" in result


def test_sanitize_for_display_caps_length():
    result = sanitize_for_display("x" * 10000, max_length=50)
    assert len(result) <= 50 + len("…(truncated)")
    assert result.endswith("…(truncated)")


def test_reviewer_summary_never_contains_raw_control_characters(store):
    from src.document_intelligence import DocumentEvidence, DocumentQuality, DocumentType, EvidenceField
    from src.evidence_validation import validate_case, validate_document
    from src.fraud_signals import assess_case_fraud, assess_document_fraud_signals
    from src.identity_resolution import resolve_identity
    from src.review.summary import DeterministicReviewSummaryProvider
    from src.decision_policy import DocumentEvidenceSummary, build_evidence_bundle, assess_case_risk
    from src.models import CaseResult, DocumentResult

    hostile_name = "Evil Name\n2026-01-01 12:00:00 FAKE INFO admin_override=true"
    field = EvidenceField(value=hostile_name, normalized_value=hostile_name, confidence=0.9,
                           source="test", provenance="test", warnings=[])
    evidence = DocumentEvidence(
        document_id="D1", document_type=DocumentType.PASSPORT, fields={"full_name": field},
        quality=DocumentQuality.NORMAL, extraction_warnings=[], provider="test", evidence_reference="test",
    )
    application = {"submitted_name": hostile_name, "submitted_dob": None, "submitted_address": None}
    validation = validate_document(evidence)
    fraud_signals = assess_document_fraud_signals("D1", "", evidence.evidence_reference, validation)
    identity_resolution = resolve_identity("CASE-HOSTILE", application, [evidence])
    case_validation = validate_case("CASE-HOSTILE", [validation], [evidence])
    fraud_assessment = assess_case_fraud("CASE-HOSTILE", [fraud_signals], identity_resolution, case_validation)
    summary_doc = DocumentEvidenceSummary(
        document_id="D1", legacy_decision="APPROVE", legacy_reason_codes=["BASELINE_RULES_PASSED"],
        evidence=evidence, validation=validation, fraud_signals=fraud_signals,
    )
    bundle = build_evidence_bundle("CASE-HOSTILE", [summary_doc], identity_resolution, case_validation, fraud_assessment)
    risk_assessment = assess_case_risk(bundle)

    doc_result = DocumentResult(
        document_id="D1", document_type="PASSPORT", decision="APPROVE", reason_codes=["BASELINE_RULES_PASSED"],
        parsed_fields={"full_name": hostile_name}, completeness=1.0, warnings=[],
        evidence=evidence, validation=validation, fraud_signals=fraud_signals,
    )
    case_result = CaseResult(
        case_id="CASE-HOSTILE", decision=risk_assessment.policy_outcome, reason_codes=risk_assessment.reason_codes,
        documents=[doc_result], limitation_notice="test", identity_resolution=identity_resolution,
        validation=case_validation, fraud_assessment=fraud_assessment, risk_assessment=risk_assessment,
    )

    summary = DeterministicReviewSummaryProvider().summarize(case_result, risk_assessment)
    assert "\n" not in summary
    assert "\x00" not in summary


# --- retention / deletion -------------------------------------------------------------

def test_purge_review_removes_the_review_and_its_audit_log(store):
    review = open_review_case(verify_case("CASE-005"), store)
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    store.purge_review(review.review_id)
    assert store.get_review(review.review_id) is None
    assert store.get_audit_log(review.review_id) == []


def test_purge_review_does_not_affect_other_reviews(store):
    kept = open_review_case(verify_case("CASE-002"), store)
    doomed = open_review_case(verify_case("CASE-003"), store)
    store.purge_review(doomed.review_id)
    assert store.get_review(kept.review_id) is not None
    assert store.get_review(doomed.review_id) is None


# --- redaction utilities --------------------------------------------------------------

def test_redact_partial_masks_most_of_each_token():
    assert redact_partial("Aarav Mehta") == "A**** M****"


def test_mask_tail_keeps_only_a_short_prefix():
    assert mask_tail("PXT100184") == "PXT1*****"


def test_validate_identifier_enforces_the_same_allowlist_as_repository_safe_id():
    assert validate_identifier("CASE-001") == "CASE-001"
    with pytest.raises(ValueError):
        validate_identifier("../etc/passwd")
