# ADR-006: Authentication scoped to the review subsystem, not core verify endpoints

**Status**: Accepted (P8), reaffirmed (P10)

## Context
P0 flagged that no endpoint in this service required authentication (finding R-18).
P8 needed to introduce an `Authorizer` abstraction and apply it somewhere concrete and
justified.

## Decision
Every `/v1/reviews*` and `/v1/cases/{id}/reviews` endpoint (read and mutate) requires
an authenticated `reviewer`-role credential. `/v1/documents/verify` and
`/v1/cases/{id}/verify` remain open.

## Consequences
- The review subsystem is where PII is aggregated for durable, human-readable
  consumption (`ReviewCase.evidence_summary`, `discrepancies`) and persisted to disk
  (ADR-003) — the highest-value, most justified place to gate access in this codebase.
- Extending auth to the core verify endpoints would require updating the calling
  convention of essentially every test written across P0-P9 (100+ tests) versus the
  ~10 that call review endpoints directly — a disproportionate blast radius for this
  stage's actual security goal.
- This is an explicit, acknowledged residual risk (not an oversight): a real
  deployment handling real applicant PII through `/v1/documents/verify`/
  `/v1/cases/{id}/verify` would need authentication there too. Documented in
  `docs/security/threat_model.md` §10 at the time of the decision and reaffirmed,
  not silently repeated, in P10's architecture review.
