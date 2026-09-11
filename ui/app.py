"""Streamlit demo UI for the AI FDE Brownfield KYC service.

Calls src/ directly, in-process -- no separate FastAPI server needed for this UI.
Everything shown here is exactly what /v1/cases/{id}/verify and /v1/reviews* return;
this file adds no new decisioning, validation, or fraud logic of its own, and reuses
the same review-workflow functions the API uses (src.review.open_review_case,
ReviewStore.apply_transition) so review actions taken here are indistinguishable, in
the durable store, from ones taken through the API.

Run: streamlit run ui/app.py  (from the repository root, with requirements-ui.txt
installed: `pip install -r requirements-ui.txt`).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.repository import list_cases  # noqa: E402
from src.review import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    ReviewNotEligibleError,
    ReviewStatus,
    get_default_review_store,
    open_review_case,
)
from src.review.errors import InvalidTransitionError  # noqa: E402
from src.security import ROLE_REVIEWER, AuthenticationError, AuthorizationError, authorize  # noqa: E402
from src.service import verify_case  # noqa: E402

st.set_page_config(page_title="AI FDE KYC — Verification Console", layout="wide")

DECISION_COLOR = {"APPROVE": "green", "REVIEW": "orange", "REJECT": "red"}


@st.cache_resource
def get_store():
    # One shared ReviewStore instance for the life of this Streamlit server process --
    # matches the FastAPI app's own get_default_review_store() lazy-singleton pattern,
    # so review state persists across reruns/interactions within one running app
    # (backed by the same var/review_store.sqlite3 file as the API, by default).
    return get_default_review_store()


def render_document(doc):
    color = DECISION_COLOR.get(doc.decision, "gray")
    with st.expander(f"{doc.document_id} — {doc.document_type} — :{color}[{doc.decision}]"):
        st.caption(f"Source: {doc.source} · Completeness: {doc.completeness:.0%}")
        if doc.warnings:
            st.warning("Warnings: " + "; ".join(doc.warnings))
        st.markdown("**Parsed fields**")
        st.table({k: v for k, v in doc.parsed_fields.items() if k != "document_type"})

        st.markdown("**Validation results**")
        rows = [
            {
                "rule_id": r.rule_id,
                "status": r.status.value,
                "severity": r.severity.value,
                "explanation": r.explanation,
            }
            for r in doc.validation.results
        ]
        st.dataframe(rows, hide_index=True, width='stretch')

        if doc.fraud_signals.signals:
            st.markdown("**Fraud signals**")
            for s in doc.fraud_signals.signals:
                st.error(f"{s.category.value} ({s.severity.value}): {s.explanation}")


def render_identity(identity):
    st.subheader("Identity resolution")
    color = {"MATCH": "green", "FUZZY_MATCH": "orange", "CONFLICT": "red",
             "INSUFFICIENT_EVIDENCE": "gray"}.get(identity.overall_status.value, "gray")
    st.markdown(f"Overall status: :{color}[{identity.overall_status.value}]  "
                f"(confidence: {identity.confidence:.2f})")
    if identity.conflicts:
        for c in identity.conflicts:
            st.error(c)
    for comparison in identity.attribute_comparisons:
        with st.expander(f"Attribute: {comparison.attribute} — {comparison.status.value}"):
            st.table([
                {"source": s.source_id, "raw_value": s.raw_value, "normalized_value": s.normalized_value}
                for s in comparison.sources
            ])
            st.markdown("**Pairwise comparisons**")
            st.table([
                {"a": p.source_a, "b": p.source_b, "status": p.status.value, "similarity": p.similarity}
                for p in comparison.pairwise
            ])


def render_risk(risk):
    st.subheader("Risk assessment & decision policy")
    color = DECISION_COLOR.get(risk.policy_outcome, "gray")
    st.markdown(f"Policy outcome: :{color}[{risk.policy_outcome}]  "
                f"(policy_version {risk.policy_version}, hard_stop_triggered={risk.hard_stop_triggered})")
    st.caption(risk.explanation)
    col1, col2, col3 = st.columns(3)
    col1.metric("Evidence strength", f"{risk.evidence_strength:.2f}")
    col2.metric("Uncertainty", f"{risk.uncertainty:.2f}")
    col3.metric("Risk factors", len(risk.risk_factors))
    if risk.risk_factors:
        st.table([
            {
                "category": f.category.value,
                "severity": f.severity.value,
                "hard_stop": f.triggers_hard_stop,
                "description": f.description,
            }
            for f in risk.risk_factors
        ])


def render_review_panel(case_result, store):
    st.subheader("Human review workflow")
    if case_result.decision != "REVIEW":
        st.info(f"This case's decision is {case_result.decision}. Only REVIEW-decision "
                "cases may open an ordinary review (no alternate route exists).")
        return

    existing = store.find_open_review_for_case(case_result.case_id)
    if existing is None and st.button("Open review case", key=f"open-{case_result.case_id}"):
        try:
            existing = open_review_case(case_result, store)
            st.success(f"Opened review {existing.review_id}")
        except ReviewNotEligibleError as e:
            st.error(str(e))

    if existing is None:
        st.caption("No open review yet for this case.")
        return

    st.markdown(f"**Review `{existing.review_id}`** — status: **{existing.status.value}**, "
                f"priority: **{existing.priority.value}**, trigger: `{existing.trigger}`")
    st.caption(existing.reviewer_summary)
    if existing.discrepancies:
        st.markdown("**Discrepancies**: " + "; ".join(existing.discrepancies))
    if existing.fraud_signals:
        st.markdown("**Fraud signals**: " + "; ".join(existing.fraud_signals))

    audit_log = store.get_audit_log(existing.review_id)
    if audit_log:
        st.markdown("**Audit trail**")
        st.dataframe(
            [{"timestamp": a.timestamp, "action": a.analyst_action, "prior": a.prior_state.value,
              "new": a.new_state.value, "rationale": a.rationale} for a in audit_log],
            hide_index=True, width='stretch',
        )

    st.markdown("---")
    st.markdown("**Reviewer action**")
    credential = st.text_input("Reviewer API key", type="password", key=f"cred-{existing.review_id}")
    allowed_next = sorted(s.value for s in ALLOWED_TRANSITIONS.get(existing.status, set()))
    if not allowed_next:
        st.caption(f"{existing.status.value} is a terminal state — no further transitions are allowed.")
        return

    with st.form(key=f"transition-{existing.review_id}"):
        new_status = st.selectbox("New status", allowed_next)
        analyst_action = st.text_input("Analyst action", max_chars=200)
        rationale = st.text_area("Rationale", max_chars=2000)
        correction = st.text_input("Correction (optional)", max_chars=2000)
        submitted = st.form_submit_button("Apply transition")

    if submitted:
        try:
            authorize(credential or None, ROLE_REVIEWER)
        except (AuthenticationError, AuthorizationError) as e:
            st.error(f"Not authorized: {e}")
            return
        if not analyst_action or not rationale:
            st.error("analyst_action and rationale are required.")
            return
        try:
            updated = store.apply_transition(
                existing.review_id, ReviewStatus(new_status), analyst_action, rationale,
                correction or None,
            )
            st.success(f"Review {updated.review_id} is now {updated.status.value}.")
            st.rerun()
        except InvalidTransitionError as e:
            st.error(str(e))


def main():
    st.title("AI FDE Brownfield KYC — Verification Console")
    st.caption("Deterministic, offline, synthetic-data-only. No LLM anywhere in the decision path — "
               "every result below is produced by the same src/ code the FastAPI service uses.")

    store = get_store()
    cases = list_cases()
    labels = {c["case_id"]: f'{c["case_id"]} — {c["scenario"]}' for c in cases}
    case_id = st.sidebar.selectbox("Synthetic case", list(labels), format_func=lambda cid: labels[cid])
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "This UI reuses src.service.verify_case() and the same review-workflow "
        "functions/store as the FastAPI API — nothing shown here is UI-only logic."
    )

    if st.sidebar.button("Run verification", type="primary") or f"result-{case_id}" in st.session_state:
        if st.session_state.get("_last_case_id") != case_id or f"result-{case_id}" not in st.session_state:
            st.session_state[f"result-{case_id}"] = verify_case(case_id)
            st.session_state["_last_case_id"] = case_id
        case_result = st.session_state[f"result-{case_id}"]

        color = DECISION_COLOR.get(case_result.decision, "gray")
        st.markdown(f"## Case {case_result.case_id}: :{color}[{case_result.decision}]")
        st.markdown("**Reason codes**: " + ", ".join(case_result.reason_codes))
        st.caption(case_result.limitation_notice)

        tab_docs, tab_identity, tab_risk, tab_review, tab_raw = st.tabs(
            ["Documents", "Identity resolution", "Risk & decision", "Review workflow", "Raw JSON"]
        )
        with tab_docs:
            for doc in case_result.documents:
                render_document(doc)
        with tab_identity:
            render_identity(case_result.identity_resolution)
        with tab_risk:
            render_risk(case_result.risk_assessment)
            with st.expander("Decision lineage"):
                st.json(case_result.decision_lineage.model_dump())
        with tab_review:
            render_review_panel(case_result, store)
        with tab_raw:
            st.json(case_result.model_dump())
    else:
        st.info("Pick a case in the sidebar and click **Run verification**.")


if __name__ == "__main__":
    main()
