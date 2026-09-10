# ADR-002: Rule-based decision policy, not a weighted risk score

**Status**: Accepted (P5)

## Context
P5 needed to replace "the worst individual document decision" with a real policy over
aggregated evidence (document decisions, identity conflicts, validation failures,
fraud signals). The obvious alternative to a rule list is a single numerical risk
score (sum of weighted contributions) thresholded into APPROVE/REVIEW/REJECT.

## Decision
Use an explicit list of `RiskFactor` objects, each with its own `triggers_hard_stop`
boolean set at the point it's derived. The policy itself
(`src/decision_policy/engine.py:_decide`) is four lines: any hard-stop factor →
REJECT; any factor at all → REVIEW; no factors → APPROVE.

## Consequences
- Every decision is traceable to specific, named factors — `RiskAssessment.risk_factors`
  is the complete, inspectable basis for the outcome, not an opaque number.
- No fixed weighting scheme has to be invented and justified for heterogeneous
  evidence (a document rejection vs. an identity conflict vs. a fraud signal aren't
  naturally comparable on one numeric scale).
- A case with many small "safe" signals cannot dilute one serious one (the failure
  mode of a weighted-sum approach) — one hard-stop factor always wins.
- `evidence_strength`/`uncertainty` (P5) still provide descriptive numeric summaries
  for analyst context, explicitly documented as **not** the decision input and **not**
  calibrated probabilities.
- Trade-off accepted: this policy cannot express "these three medium-severity signals
  together should escalate to REJECT even though none alone would." If that nuance is
  needed later, it should be added as an explicit new rule (e.g. "3+ MEDIUM factors of
  different categories is itself a hard-stop condition"), not a re-introduction of
  weighted scoring — keeping every rule individually nameable and testable.
