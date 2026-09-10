"""P10: architecture/coupling checks, provider-interface conformance, graceful
lifecycle, idempotency, and a real (not claimed) concurrency smoke test.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.app as appmod
from src.providers import (
    ExternalFraudSignalProvider,
    ExternalIdentityVerificationProvider,
    NullExternalFraudSignalProvider,
    NullExternalIdentityProvider,
    ProviderUnavailableError,
    call_with_retries,
)
from src.review import ReviewRepository, ReviewStore
from src.security import review_transition_idempotency_cache, review_transition_rate_limiter

SRC = Path(__file__).resolve().parents[1] / "src"


# --- import graph: no circular dependencies, no layering violations ----------------

def _build_import_graph() -> dict[str, set[str]]:
    """Maps each top-level src/ package/module to the set of other top-level src/
    packages/modules it imports from (via relative imports), so we can check for
    cycles and specific layering rules programmatically rather than by inspection."""
    graph: dict[str, set[str]] = {}
    top_level_names = {p.stem if p.is_file() else p.name for p in SRC.iterdir() if p.name != "__pycache__"}

    for py_file in SRC.rglob("*.py"):
        rel = py_file.relative_to(SRC)
        is_nested = len(rel.parts) > 1  # file lives inside a subpackage, e.g. src/identity_resolution/matching.py
        owner = rel.parts[0] if is_nested else rel.stem
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            # level == 1 ('from .x import y') from a file already inside a subpackage
            # always refers to a SIBLING SUBMODULE of that same subpackage (e.g.
            # identity_resolution/matching.py's 'from .models import X' means
            # identity_resolution.models, never the top-level src/models.py) --
            # never a cross-top-level-package edge, regardless of whether the
            # submodule's name collides with an unrelated top-level module's name.
            if node.level == 1 and is_nested:
                continue
            if node.module:
                target = node.module.split(".")[0]
            else:
                continue
            if target in top_level_names and target != owner:
                graph.setdefault(owner, set()).add(target)
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting, visited = set(), set()

    def dfs(node, path):
        if node in visiting:
            return path + [node]
        if node in visited:
            return None
        visiting.add(node)
        for neighbor in graph.get(node, ()):
            result = dfs(neighbor, path + [node])
            if result:
                return result
        visiting.discard(node)
        visited.add(node)
        return None

    for node in graph:
        result = dfs(node, [])
        if result:
            return result
    return None


def test_no_circular_imports_across_src_packages():
    graph = _build_import_graph()
    cycle = _find_cycle(graph)
    assert cycle is None, f"circular import detected: {' -> '.join(cycle) if cycle else cycle}"


def test_document_intelligence_does_not_depend_on_decisioning_module():
    # P10 finding: document_intelligence/evidence_validation/fraud_signals previously
    # imported shared constants (PATTERNS, TAMPER_MARKER) from src.rules -- decisioning's
    # own module -- purely to avoid duplication. Fixed by moving those constants to the
    # already-neutral src.policy leaf. This test guards against the coupling regressing.
    graph = _build_import_graph()
    assert "rules" not in graph.get("document_intelligence", set())
    assert "rules" not in graph.get("fraud_signals", set())


def test_shared_domain_constants_have_one_home():
    from src import policy, rules

    assert rules.PATTERNS is policy.PATTERNS
    assert rules.TAMPER_MARKER is policy.TAMPER_MARKER


# --- provider abstractions (P10 requirement 4) --------------------------------------

def test_review_store_implements_the_review_repository_interface():
    assert issubclass(ReviewStore, ReviewRepository)
    store = ReviewStore(":memory:")
    assert isinstance(store, ReviewRepository)


def test_null_external_identity_provider_conforms_to_its_interface():
    provider = NullExternalIdentityProvider()
    assert isinstance(provider, ExternalIdentityVerificationProvider)
    result = provider.verify("Test Person", "1990-01-01", "PXT100184")
    assert result.status == "NOT_IMPLEMENTED"
    assert result.provider == provider.name


def test_null_external_fraud_signal_provider_conforms_and_returns_no_fabricated_signals():
    provider = NullExternalFraudSignalProvider()
    assert isinstance(provider, ExternalFraudSignalProvider)
    assert provider.assess("CASE-001") == []


def test_call_with_retries_succeeds_after_transient_failures():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("simulated transient failure")
        return "ok"

    result = call_with_retries(flaky, max_attempts=5, backoff_seconds=0.001)
    assert result == "ok"
    assert attempts["count"] == 3


def test_call_with_retries_raises_provider_unavailable_after_exhausting_attempts():
    def always_fails():
        raise ConnectionError("simulated permanent failure")

    with pytest.raises(ProviderUnavailableError):
        call_with_retries(always_fails, max_attempts=3, backoff_seconds=0.001)


# --- graceful startup/shutdown (P10 requirement 10) ---------------------------------

def test_lifespan_startup_and_shutdown_emit_events(caplog):
    import logging

    import src.review as review_mod

    # Using TestClient as a context manager actually runs the lifespan handler,
    # which closes the shared default review-store singleton's SQLite connection on
    # exit. Reset the singleton afterward so this test doesn't leave a closed
    # connection behind for every other test in the same pytest process that calls
    # get_default_review_store() (a real test-isolation hazard this test itself
    # surfaced while verifying the shutdown behavior it's checking).
    try:
        with caplog.at_level(logging.INFO):
            with TestClient(appmod.app) as client:
                r = client.get("/health/live")
                assert r.status_code == 200
        messages = [record.getMessage() for record in caplog.records]
        assert any("startup" in m for m in messages)
        assert any("shutdown" in m for m in messages)
    finally:
        review_mod._default_store = None


# --- idempotency (P10 requirement 10) ------------------------------------------------

def test_repeated_transition_with_the_same_idempotency_key_is_not_reapplied():
    review_transition_idempotency_cache.reset()
    store = ReviewStore(":memory:")
    appmod.app.dependency_overrides[appmod.review_store_dependency] = lambda: store
    try:
        client = TestClient(appmod.app)
        headers = {"X-API-Key": "workshop-reviewer-key"}
        opened = client.post("/v1/cases/CASE-005/reviews", headers=headers).json()
        review_id = opened["review_id"]

        idem_headers = {**headers, "Idempotency-Key": "retry-key-1"}
        body = {"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "test"}
        first = client.post(f"/v1/reviews/{review_id}/transitions", headers=idem_headers, json=body)
        second = client.post(f"/v1/reviews/{review_id}/transitions", headers=idem_headers, json=body)

        assert first.status_code == 200 and second.status_code == 200
        assert first.json() == second.json()
        history = client.get(f"/v1/reviews/{review_id}/history", headers=headers).json()
        assert len(history) == 1  # not re-applied a second time
    finally:
        appmod.app.dependency_overrides.clear()
        review_transition_idempotency_cache.reset()


def test_different_idempotency_keys_are_not_conflated():
    review_transition_rate_limiter.reset()
    store = ReviewStore(":memory:")
    appmod.app.dependency_overrides[appmod.review_store_dependency] = lambda: store
    try:
        client = TestClient(appmod.app)
        headers = {"X-API-Key": "workshop-reviewer-key"}
        opened = client.post("/v1/cases/CASE-005/reviews", headers=headers).json()
        review_id = opened["review_id"]

        client.post(
            f"/v1/reviews/{review_id}/transitions",
            headers={**headers, "Idempotency-Key": "key-a"},
            json={"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "a"},
        )
        second = client.post(
            f"/v1/reviews/{review_id}/transitions",
            headers={**headers, "Idempotency-Key": "key-b"},
            json={"new_status": "RESOLVED", "analyst_action": "clear", "rationale": "b"},
        )
        assert second.status_code == 200
        assert second.json()["status"] == "RESOLVED"
    finally:
        appmod.app.dependency_overrides.clear()
        review_transition_rate_limiter.reset()


def test_concurrent_retries_with_the_same_idempotency_key_never_409():
    """P11 red-team regression: firing N concurrent requests with the same
    Idempotency-Key used to let a retry land in the window between another thread's
    store mutation and its cache write, so the loser re-ran the transition against
    already-mutated state and got a 409 instead of the cached success. Every retry of
    the same key must observe the one successful result, never an error, and the
    transition must be applied exactly once."""
    review_transition_idempotency_cache.reset()
    review_transition_rate_limiter.reset()  # 8 concurrent calls stay well under the default limit of 20
    store = ReviewStore(":memory:")
    appmod.app.dependency_overrides[appmod.review_store_dependency] = lambda: store
    try:
        client = TestClient(appmod.app)
        headers = {"X-API-Key": "workshop-reviewer-key"}
        opened = client.post("/v1/cases/CASE-005/reviews", headers=headers).json()
        review_id = opened["review_id"]

        idem_headers = {**headers, "Idempotency-Key": "concurrent-retry-key"}
        body = {"new_status": "IN_REVIEW", "analyst_action": "start", "rationale": "concurrent retry"}

        def fire(_):
            return client.post(f"/v1/reviews/{review_id}/transitions", headers=idem_headers, json=body)

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(fire, range(8)))

        assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
        bodies = [r.json() for r in responses]
        assert all(b == bodies[0] for b in bodies)
        history = client.get(f"/v1/reviews/{review_id}/history", headers=headers).json()
        assert len(history) == 1
    finally:
        appmod.app.dependency_overrides.clear()
        review_transition_idempotency_cache.reset()
        review_transition_rate_limiter.reset()


# --- concurrency: a real, measured smoke test (P10 requirement 12: no unverified claims) --

def test_concurrent_verify_requests_succeed_without_error_or_corruption():
    """Not a load test and not a capacity claim (P10 requirement 12) -- this proves
    the code has no functional concurrency defect (no exception, no cross-request
    data bleed) under a modest, real, measured concurrent workload on a single
    machine via TestClient's in-process ASGI transport. It says nothing about
    production network/multi-process throughput; see docs/architecture/overview.md's
    concurrency section for what would need real load testing to claim."""
    client = TestClient(appmod.app)
    case_ids = ["CASE-001", "CASE-002", "CASE-003", "CASE-004", "CASE-005", "CASE-006"]
    expected_decisions = {
        "CASE-001": "APPROVE", "CASE-002": "REVIEW", "CASE-003": "REVIEW",
        "CASE-004": "REJECT", "CASE-005": "REVIEW", "CASE-006": "REJECT",
    }

    def verify_one(i):
        case_id = case_ids[i % len(case_ids)]
        response = client.post(f"/v1/cases/{case_id}/verify")
        return case_id, response.status_code, response.json().get("decision")

    request_count = 60
    with ThreadPoolExecutor(max_workers=15) as pool:
        results = list(pool.map(verify_one, range(request_count)))

    assert len(results) == request_count
    for case_id, status_code, decision in results:
        assert status_code == 200, f"{case_id} returned {status_code} under concurrent load"
        assert decision == expected_decisions[case_id], (
            f"{case_id} returned {decision} under concurrent load, expected "
            f"{expected_decisions[case_id]} -- possible cross-request state bleed"
        )
