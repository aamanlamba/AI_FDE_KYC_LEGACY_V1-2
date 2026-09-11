"""Smoke tests for the Streamlit UI (ui/app.py).

This does not re-test business logic already covered by tests/test_service.py,
tests/test_review.py, etc. -- it proves the UI's wiring is correct: that it imports
cleanly, renders real verification/review data without raising, and that its
review-transition form actually calls through to the same authorize()/apply_transition()
the API uses rather than bypassing them.

Skipped entirely if streamlit isn't installed (it's an optional UI dependency in
requirements-ui.txt, deliberately not part of requirements.txt/requirements-dev.txt --
see that file's own comment -- so CI and a plain `pip install -r requirements.txt`
never need it and this file must not break collection when it's absent).

ui/app.py's get_store() is @st.cache_resource, and get_default_review_store()/
get_default_authorizer() are both lazy singletons -- all three are created once and
cached for the life of the Python process, not per AppTest instance. Within a single
running app (or one AppTest instance across repeated .run() calls) that's exactly the
intended behavior; across separate test functions in the same pytest process it would
silently leak one test's review store/credentials into the next, so the ui_env fixture
below resets all three explicitly instead of relying on REVIEW_DB_PATH/REVIEWER_API_KEYS
alone.
"""

import sqlite3
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

REVIEWER_KEY = "test-ui-reviewer-key"
APP_PATH = str(Path(__file__).resolve().parents[1] / "ui" / "app.py")


@pytest.fixture
def ui_env(tmp_path, monkeypatch):
    # Two layers of process-wide caching stand between REVIEW_DB_PATH and an
    # isolated per-test store, neither scoped to one AppTest instance:
    #   1. ui/app.py's get_store() is @st.cache_resource -- streamlit's cache lives
    #      at the package level, so a store cached by an earlier test would leak in.
    #   2. get_default_review_store()'s own _default_store singleton, and
    #      ReviewStore's default db_path parameter, are both bound once at first
    #      import in this pytest process -- re-setting the env var after that point
    #      has no effect on either.
    # Clearing (1) and directly replacing (2) with a store built from THIS test's
    # explicit path sidesteps both, without changing any production code.
    st.cache_resource.clear()
    db_path = tmp_path / "ui_review_store.sqlite3"
    monkeypatch.setenv("REVIEW_DB_PATH", str(db_path))
    monkeypatch.setenv("REVIEWER_API_KEYS", REVIEWER_KEY)

    import src.review as review_mod
    import src.security.auth as auth_mod
    from src.review import ReviewStore

    review_mod._default_store = ReviewStore(str(db_path))
    # Same frozen-singleton issue applies to the default Authorizer: it's built once
    # from whatever REVIEWER_API_KEYS an earlier test in this process set, and never
    # invalidated. Reset it so authorize() picks up THIS test's credential.
    auth_mod._default_authorizer = None
    yield db_path
    review_mod._default_store = None
    auth_mod._default_authorizer = None


def _select_case(at, label: str):
    at.sidebar.selectbox[0].select(label)
    at.sidebar.button[0].click()
    at.run()


def test_app_loads_without_exception_before_any_interaction(ui_env):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Pick a case" in m.value for m in at.info)


def test_approve_case_renders_full_result_without_exception(ui_env):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    _select_case(at, "CASE-001 — clean")
    assert not at.exception
    assert any("APPROVE" in m.value for m in at.markdown if m.value.startswith("## Case"))
    # Review tab should say this case is not eligible for the ordinary review workflow.
    review_tab = at.tabs[3]
    assert any("Only REVIEW-decision cases" in m.value for m in review_tab.info)


def test_review_case_renders_identity_conflict_and_risk_factors(ui_env):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    _select_case(at, "CASE-005 — name_variation_ocr_error")
    assert not at.exception
    assert any("REVIEW" in m.value for m in at.markdown if m.value.startswith("## Case"))
    identity_tab = at.tabs[1]
    assert any("CONFLICT" in m.value for m in identity_tab.markdown)
    risk_tab = at.tabs[2]
    assert len(risk_tab.table) >= 1  # the risk_factors table rendered


def test_full_review_workflow_end_to_end_through_the_ui(ui_env):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    _select_case(at, "CASE-005 — name_variation_ocr_error")
    review_tab = at.tabs[3]

    open_key = next(b.key for b in review_tab.button if b.label == "Open review case")
    review_tab.button(key=open_key).click()
    at.run()
    assert not at.exception
    assert any("Opened review" in m.value for m in at.success)

    review_tab = at.tabs[3]
    cred_key = next(ti.key for ti in review_tab.text_input if ti.label == "Reviewer API key")
    action_key = next(ti.key for ti in review_tab.text_input if ti.label == "Analyst action")
    review_tab.text_input(key=cred_key).set_value(REVIEWER_KEY)
    review_tab.text_input(key=action_key).set_value("start-review")
    review_tab.text_area[0].set_value("looks fine, escalating for manual check")
    review_tab.selectbox[0].select("IN_REVIEW")
    submit_key = next(b.key for b in review_tab.button if b.label == "Apply transition")
    review_tab.button(key=submit_key).click()
    at.run()
    assert not at.exception
    # at.error also always carries the case's genuine identity-conflict message
    # (rendered in the Identity Resolution tab, present regardless of this
    # transition's outcome, since all tabs render on every script run) -- check
    # specifically for the transition-rejection messages this step could produce.
    assert not any("Not authorized" in e.value or "are required" in e.value for e in at.error), \
        [e.value for e in at.error]

    conn = sqlite3.connect(ui_env)
    try:
        rows = conn.execute("SELECT case_id, status FROM review_cases").fetchall()
        audit = conn.execute(
            "SELECT analyst_action, prior_state, new_state FROM review_audit_log"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("CASE-005", "IN_REVIEW")]
    assert audit == [("start-review", "OPEN", "IN_REVIEW")]


def test_transition_is_rejected_without_a_valid_reviewer_credential(ui_env):
    """The UI must not let a transition through on an empty/wrong credential -- it has
    to call the same authorize() the API uses, not just decorate the form."""
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    _select_case(at, "CASE-005 — name_variation_ocr_error")
    review_tab = at.tabs[3]
    open_key = next(b.key for b in review_tab.button if b.label == "Open review case")
    review_tab.button(key=open_key).click()
    at.run()

    review_tab = at.tabs[3]
    action_key = next(ti.key for ti in review_tab.text_input if ti.label == "Analyst action")
    review_tab.text_input(key=action_key).set_value("start-review")
    review_tab.text_area[0].set_value("attempting without credential")
    review_tab.selectbox[0].select("IN_REVIEW")
    submit_key = next(b.key for b in review_tab.button if b.label == "Apply transition")
    review_tab.button(key=submit_key).click()
    at.run()

    assert not at.exception
    assert any("Not authorized" in e.value for e in at.error)
    conn = sqlite3.connect(ui_env)
    try:
        rows = conn.execute("SELECT status FROM review_cases").fetchall()
    finally:
        conn.close()
    assert rows == [("OPEN",)]  # unchanged -- the rejected attempt had no side effect
