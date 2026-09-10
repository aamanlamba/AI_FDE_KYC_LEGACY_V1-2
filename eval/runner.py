import time
from dataclasses import dataclass, field

from src.document_intelligence import DocumentEvidence
from src.identity_resolution import MatchStatus
from src.policy import Decision
from src.service import verify_case

from .cases import EvalCase
from .pipeline import run_synthetic_case


@dataclass
class CaseRunRecord:
    case: EvalCase
    decision: Decision | None = None
    reason_codes: list[str] = field(default_factory=list)
    identity_overall_status: str | None = None
    has_identity_conflict: bool = False
    documents_evidence: list[DocumentEvidence] = field(default_factory=list)
    exception: BaseException | None = None
    latency_seconds: float = 0.0

    @property
    def raised(self) -> bool:
        return self.exception is not None

    @property
    def exception_was_expected(self) -> bool:
        if self.case.expect_exception is None:
            return self.exception is None
        return isinstance(self.exception, self.case.expect_exception)


def run_eval_case(eval_case: EvalCase) -> CaseRunRecord:
    record = CaseRunRecord(case=eval_case)
    start = time.perf_counter()
    try:
        if eval_case.source == "repository":
            result = verify_case(eval_case.repo_case_id)
            record.decision = result.decision
            record.reason_codes = result.reason_codes
            record.identity_overall_status = result.identity_resolution.overall_status.value
            record.has_identity_conflict = any(
                ac.status == MatchStatus.CONFLICT for ac in result.identity_resolution.attribute_comparisons
            )
            record.documents_evidence = [d.evidence for d in result.documents]
        else:
            application, documents, raw_texts, legacy_decisions = eval_case.build_synthetic()
            synthetic_result = run_synthetic_case(eval_case.case_id, application, documents, raw_texts, legacy_decisions)
            record.decision = synthetic_result.decision
            record.reason_codes = synthetic_result.reason_codes
            record.identity_overall_status = synthetic_result.identity_resolution.overall_status.value
            record.has_identity_conflict = any(
                ac.status == MatchStatus.CONFLICT for ac in synthetic_result.identity_resolution.attribute_comparisons
            )
            record.documents_evidence = documents
    except BaseException as exc:  # noqa: BLE001 -- the harness must observe every exception, not just Exception subclasses
        record.exception = exc
    record.latency_seconds = time.perf_counter() - start
    return record


def run_all(eval_cases: list[EvalCase]) -> list[CaseRunRecord]:
    return [run_eval_case(c) for c in eval_cases]
