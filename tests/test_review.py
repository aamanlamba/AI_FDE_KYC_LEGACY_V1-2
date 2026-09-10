import pytest
from fastapi.testclient import TestClient

import src.app as appmod
from src.review import (
    InvalidTransitionError,
    ReviewNotEligibleError,
    ReviewNotFoundError,
    ReviewStatus,
    ReviewStore,
    open_review_case,
)
from src.service import verify_case


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


# --- opening a review: eligibility and grounding ------------------------------------

def test_only_review_decisions_may_open_an_ordinary_review(store):
    approved_case = verify_case("CASE-001")  # decision == APPROVE
    with pytest.raises(ReviewNotEligibleError):
        open_review_case(approved_case, store)


def test_rejected_case_also_cannot_open_an_ordinary_review(store):
    rejected_case = verify_case("CASE-006")  # decision == REJECT
    with pytest.raises(ReviewNotEligibleError):
        open_review_case(rejected_case, store)


def test_review_case_is_grounded_in_actual_case_evidence(store):
    case_result = verify_case("CASE-005")
    review = open_review_case(case_result, store)
    assert review.case_id == "CASE-005"
    assert review.policy_version == case_result.risk_assessment.policy_version
    assert review.reason_codes == case_result.reason_codes
    assert review.status == ReviewStatus.OPEN
    # discrepancies/fraud_signals must trace back to what was actually computed --
    # not fabricated text.
    assert any("full_name" in d for d in review.discrepancies)
    assert any("identity_conflict" in fs for fs in review.fraud_signals)
    assert "CASE-005" in review.reviewer_summary


def test_opening_review_twice_for_the_same_case_returns_the_same_record(store):
    case_result = verify_case("CASE-005")
    first = open_review_case(case_result, store)
    second = open_review_case(case_result, store)
    assert first.review_id == second.review_id
    assert len(store.list_reviews()) == 1


def test_priority_reflects_highest_severity_risk_factor(store):
    case_result = verify_case("CASE-005")  # HIGH-severity identity_conflict factor
    review = open_review_case(case_result, store)
    assert review.priority.value == "HIGH"
    assert review.trigger == "identity_conflict"


# --- durable persistence (SQLite) ----------------------------------------------------

def test_review_persists_across_separate_store_instances_backed_by_the_same_file(tmp_path):
    db_path = tmp_path / "review.sqlite3"
    store1 = ReviewStore(db_path)
    case_result = verify_case("CASE-002")
    review = open_review_case(case_result, store1)

    store2 = ReviewStore(db_path)  # a fresh connection to the same on-disk file
    reloaded = store2.get_review(review.review_id)
    assert reloaded is not None
    assert reloaded.case_id == "CASE-002"
    assert reloaded.model_dump() == review.model_dump()


# --- lifecycle transitions (requirement 11) -------------------------------------------

def test_full_lifecycle_open_to_in_review_to_resolved(store):
    review = open_review_case(verify_case("CASE-005"), store)
    updated = store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    assert updated.status == ReviewStatus.IN_REVIEW
    resolved = store.apply_transition(
        review.review_id, ReviewStatus.RESOLVED, "clear", "verified manually against secondary ID",
        correction="full_name confirmed as Mohammad Rehman across documents",
    )
    assert resolved.status == ReviewStatus.RESOLVED


def test_full_lifecycle_open_to_in_review_to_escalated(store):
    review = open_review_case(verify_case("CASE-005"), store)
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    escalated = store.apply_transition(review.review_id, ReviewStatus.ESCALATED, "escalate", "needs compliance sign-off")
    assert escalated.status == ReviewStatus.ESCALATED


def test_audit_log_captures_every_field_and_is_append_only(store):
    review = open_review_case(verify_case("CASE-005"), store)
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    store.apply_transition(
        review.review_id, ReviewStatus.RESOLVED, "clear", "verified", correction="name confirmed"
    )
    log = store.get_audit_log(review.review_id)
    assert len(log) == 2
    assert log[0].prior_state == ReviewStatus.OPEN and log[0].new_state == ReviewStatus.IN_REVIEW
    assert log[1].prior_state == ReviewStatus.IN_REVIEW and log[1].new_state == ReviewStatus.RESOLVED
    assert log[1].correction == "name confirmed"
    assert log[1].rationale == "verified"
    assert log[1].timestamp


def test_correction_does_not_mutate_the_original_review_snapshot(store):
    review = open_review_case(verify_case("CASE-005"), store)
    original_discrepancies = list(review.discrepancies)
    original_summary = review.reviewer_summary
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    updated = store.apply_transition(
        review.review_id, ReviewStatus.RESOLVED, "clear", "verified",
        correction="the extracted name was OCR-corrupted; true name confirmed manually",
    )
    # The correction is recorded in the audit log only -- the review's own evidence
    # snapshot (captured at creation) is untouched by it.
    assert updated.discrepancies == original_discrepancies
    assert updated.reviewer_summary == original_summary


# --- invalid states --------------------------------------------------------------------

def test_skipping_a_state_is_rejected(store):
    review = open_review_case(verify_case("CASE-005"), store)
    with pytest.raises(InvalidTransitionError):
        store.apply_transition(review.review_id, ReviewStatus.RESOLVED, "skip", "trying to skip IN_REVIEW")


def test_transitioning_from_a_terminal_state_is_rejected(store):
    review = open_review_case(verify_case("CASE-005"), store)
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    store.apply_transition(review.review_id, ReviewStatus.RESOLVED, "clear", "verified")
    with pytest.raises(InvalidTransitionError):
        store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "reopen", "changed my mind")


def test_transition_on_unknown_review_id_raises_not_found(store):
    with pytest.raises(ReviewNotFoundError):
        store.apply_transition("RVW-DOES-NOT-EXIST", ReviewStatus.IN_REVIEW, "start", "n/a")


def test_state_unaffected_after_a_rejected_transition(store):
    review = open_review_case(verify_case("CASE-005"), store)
    with pytest.raises(InvalidTransitionError):
        store.apply_transition(review.review_id, ReviewStatus.RESOLVED, "skip", "invalid")
    assert store.get_review(review.review_id).status == ReviewStatus.OPEN


# --- duplicate actions -------------------------------------------------------------------

def test_duplicate_start_review_action_is_rejected_the_second_time(store):
    review = open_review_case(verify_case("CASE-005"), store)
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    # The same "move to IN_REVIEW" action submitted again (e.g. a retried request) is
    # now an invalid transition (IN_REVIEW -> IN_REVIEW is not allowed) and is rejected,
    # not silently applied twice or double-logged.
    with pytest.raises(InvalidTransitionError):
        store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    assert len(store.get_audit_log(review.review_id)) == 1


def test_duplicate_resolve_action_is_rejected(store):
    review = open_review_case(verify_case("CASE-005"), store)
    store.apply_transition(review.review_id, ReviewStatus.IN_REVIEW, "start", "picking up case")
    store.apply_transition(review.review_id, ReviewStatus.RESOLVED, "clear", "verified")
    with pytest.raises(InvalidTransitionError):
        store.apply_transition(review.review_id, ReviewStatus.RESOLVED, "clear", "verified again")
    assert len(store.get_audit_log(review.review_id)) == 2  # not 3


# --- listing / filtering ------------------------------------------------------------------

def test_list_reviews_filters_by_status(store):
    r1 = open_review_case(verify_case("CASE-002"), store)
    r2 = open_review_case(verify_case("CASE-003"), store)
    store.apply_transition(r1.review_id, ReviewStatus.IN_REVIEW, "start", "picking up")
    open_only = store.list_reviews(ReviewStatus.OPEN)
    in_review_only = store.list_reviews(ReviewStatus.IN_REVIEW)
    assert {r.review_id for r in open_only} == {r2.review_id}
    assert {r.review_id for r in in_review_only} == {r1.review_id}


# --- API endpoints (additive paths) --------------------------------------------------------

def test_api_open_review_for_review_case(client):
    r = client.post("/v1/cases/CASE-005/reviews")
    assert r.status_code == 201
    assert r.json()["status"] == "OPEN"


def test_api_open_review_for_non_review_case_returns_409(client):
    r = client.post("/v1/cases/CASE-001/reviews")
    assert r.status_code == 409


def test_api_get_unknown_review_returns_404(client):
    r = client.get("/v1/reviews/RVW-DOES-NOT-EXIST")
    assert r.status_code == 404


def test_api_full_lifecycle_via_http(client):
    opened = client.post("/v1/cases/CASE-005/reviews").json()
    review_id = opened["review_id"]

    in_review = client.post(
        f"/v1/reviews/{review_id}/transitions",
        json={"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "picking up case"},
    )
    assert in_review.status_code == 200 and in_review.json()["status"] == "IN_REVIEW"

    resolved = client.post(
        f"/v1/reviews/{review_id}/transitions",
        json={"new_status": "RESOLVED", "analyst_action": "clear", "rationale": "verified manually"},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVED"

    invalid = client.post(
        f"/v1/reviews/{review_id}/transitions",
        json={"new_status": "IN_REVIEW", "analyst_action": "reopen", "rationale": "n/a"},
    )
    assert invalid.status_code == 409

    history = client.get(f"/v1/reviews/{review_id}/history")
    assert history.status_code == 200 and len(history.json()) == 2


def test_api_legacy_endpoints_are_unaffected(client):
    # requirement 7/8-style regression: new paths must not disturb existing ones.
    r = client.post("/v1/documents/verify", json={"document_id": "CASE-001-PASSPORT"})
    assert r.status_code == 200 and r.json()["decision"] == "APPROVE"
    r2 = client.post("/v1/cases/CASE-006/verify")
    assert r2.status_code == 200 and r2.json()["decision"] == "REJECT"


# --- reviewer summary is grounded, not fabricated ------------------------------------------

def test_reviewer_summary_never_mentions_documents_not_in_the_case(store):
    case_result = verify_case("CASE-002")
    review = open_review_case(case_result, store)
    assert "CASE-002" in review.reviewer_summary
    # no fabricated document/case id should appear
    assert "CASE-999" not in review.reviewer_summary
