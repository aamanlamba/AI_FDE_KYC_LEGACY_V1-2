import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .errors import InvalidTransitionError, ReviewNotFoundError
from .models import ALLOWED_TRANSITIONS, EvidenceSummary, ReviewAuditEntry, ReviewCase, ReviewStatus

_ROOT = Path(__file__).resolve().parents[2]
# Overridable via REVIEW_DB_PATH (e.g. by scripts/smoke_server.py, to keep smoke runs
# hermetic rather than accumulating rows in the shared workshop database file).
DEFAULT_DB_PATH = Path(os.environ.get("REVIEW_DB_PATH", str(_ROOT / "var" / "review_store.sqlite3")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_cases (
    review_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    trigger_category TEXT NOT NULL,
    priority TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    discrepancies TEXT NOT NULL,
    failed_validations TEXT NOT NULL,
    fraud_signals TEXT NOT NULL,
    reason_codes TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    reviewer_summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL,
    analyst_action TEXT NOT NULL,
    correction TEXT,
    rationale TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    prior_state TEXT NOT NULL,
    new_state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_audit_log_review_id ON review_audit_log(review_id);
"""


def _review_from_row(row: sqlite3.Row) -> ReviewCase:
    return ReviewCase(
        review_id=row["review_id"],
        case_id=row["case_id"],
        trigger=row["trigger_category"],
        priority=row["priority"],
        evidence_summary=EvidenceSummary.model_validate_json(row["evidence_summary"]),
        discrepancies=json.loads(row["discrepancies"]),
        failed_validations=json.loads(row["failed_validations"]),
        fraud_signals=json.loads(row["fraud_signals"]),
        reason_codes=json.loads(row["reason_codes"]),
        status=row["status"],
        created_at=row["created_at"],
        policy_version=row["policy_version"],
        reviewer_summary=row["reviewer_summary"],
    )


def _audit_entry_from_row(row: sqlite3.Row) -> ReviewAuditEntry:
    return ReviewAuditEntry(
        review_id=row["review_id"],
        analyst_action=row["analyst_action"],
        correction=row["correction"],
        rationale=row["rationale"],
        timestamp=row["timestamp"],
        prior_state=row["prior_state"],
        new_state=row["new_state"],
    )


class ReviewStore:
    """Durable local persistence for review cases (SQLite -- appropriate for a
    locally-runnable workshop service; no external database required).

    review_cases.status is the only mutable field on a persisted review. Every change
    to it is preceded by an insert-only row in review_audit_log, so the full state
    history is always reconstructable even though "current status" is a live pointer.

    Holds one persistent connection for the store's lifetime (required for ":memory:"
    databases, which are otherwise a fresh empty database on every new connection) and
    guards it with a lock, since FastAPI runs sync endpoints across a thread pool.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def create_review(self, review: ReviewCase) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO review_cases (review_id, case_id, trigger_category, priority, "
                "evidence_summary, discrepancies, failed_validations, fraud_signals, reason_codes, "
                "status, created_at, policy_version, reviewer_summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    review.review_id, review.case_id, review.trigger, review.priority.value,
                    review.evidence_summary.model_dump_json(), json.dumps(review.discrepancies),
                    json.dumps(review.failed_validations), json.dumps(review.fraud_signals),
                    json.dumps(review.reason_codes), review.status.value, review.created_at,
                    review.policy_version, review.reviewer_summary,
                ),
            )
            self._conn.commit()

    def get_review(self, review_id: str) -> ReviewCase | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM review_cases WHERE review_id = ?", (review_id,)).fetchone()
        return _review_from_row(row) if row else None

    def find_open_review_for_case(self, case_id: str) -> ReviewCase | None:
        """The most recent non-terminal (OPEN/IN_REVIEW) review for this case, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM review_cases WHERE case_id = ? AND status IN (?, ?) "
                "ORDER BY created_at DESC LIMIT 1",
                (case_id, ReviewStatus.OPEN.value, ReviewStatus.IN_REVIEW.value),
            ).fetchone()
        return _review_from_row(row) if row else None

    def list_reviews(self, status: ReviewStatus | None = None) -> list[ReviewCase]:
        with self._lock:
            if status is not None:
                rows = self._conn.execute(
                    "SELECT * FROM review_cases WHERE status = ? ORDER BY created_at", (status.value,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM review_cases ORDER BY created_at").fetchall()
        return [_review_from_row(r) for r in rows]

    def get_audit_log(self, review_id: str) -> list[ReviewAuditEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM review_audit_log WHERE review_id = ? ORDER BY id", (review_id,)
            ).fetchall()
        return [_audit_entry_from_row(r) for r in rows]

    def apply_transition(
        self,
        review_id: str,
        new_status: ReviewStatus,
        analyst_action: str,
        rationale: str,
        correction: str | None = None,
    ) -> ReviewCase:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            row = self._conn.execute("SELECT status FROM review_cases WHERE review_id = ?", (review_id,)).fetchone()
            if row is None:
                raise ReviewNotFoundError(review_id)
            prior_status = ReviewStatus(row["status"])
            if new_status not in ALLOWED_TRANSITIONS.get(prior_status, set()):
                raise InvalidTransitionError(
                    f"cannot transition review {review_id} from {prior_status.value} to {new_status.value}"
                )
            self._conn.execute(
                "UPDATE review_cases SET status = ? WHERE review_id = ?", (new_status.value, review_id)
            )
            self._conn.execute(
                "INSERT INTO review_audit_log (review_id, analyst_action, correction, rationale, "
                "timestamp, prior_state, new_state) VALUES (?,?,?,?,?,?,?)",
                (review_id, analyst_action, correction, rationale, timestamp, prior_status.value, new_status.value),
            )
            self._conn.commit()
        return self.get_review(review_id)

    def purge_review(self, review_id: str) -> None:
        """Hard-deletes a review and its full audit trail. This is the retention/
        deletion primitive referenced in docs/security/privacy_data_flow.md -- the
        review workflow durably stores identity attributes (evidence_summary,
        discrepancies, fraud_signals may embed names) to disk, so a deletion path must
        exist. No API endpoint exposes this in the current stage (deliberately
        documented as a residual scope boundary, not silently omitted); it is exercised
        directly today by an operator/script, or by a future admin-authenticated
        endpoint built on this same primitive.
        """
        with self._lock:
            self._conn.execute("DELETE FROM review_audit_log WHERE review_id = ?", (review_id,))
            self._conn.execute("DELETE FROM review_cases WHERE review_id = ?", (review_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
