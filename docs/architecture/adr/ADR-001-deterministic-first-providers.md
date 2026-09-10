# ADR-001: Deterministic-first provider pattern

**Status**: Accepted (established P1, applied consistently through P10)

## Context
This repository must run fully offline, reproducibly, with no external API keys
(CLAUDE.md rules 6-8). At the same time, every extraction/fraud/summarization/auth
capability needs a seam where a real, network-backed implementation could later be
substituted.

## Decision
Every capability that could plausibly be backed by an external service is expressed
as an abstract interface (`DocumentIntelligenceProvider`, `DocumentForensicsProvider`,
`ReviewSummaryProvider`, `Authorizer`, `ReviewRepository`,
`ExternalIdentityVerificationProvider`, `ExternalFraudSignalProvider`), with a
deterministic, offline, first-class implementation as the only one actually used. A
caller (`src/service.py`, `src/app.py`) depends only on the interface.

## Consequences
- The deterministic implementation is never treated as a "mock" or "stub" to be
  deleted later — it's a legitimate, fully-tested, first-class implementation choice
  appropriate for this deployment context (CLAUDE.md rule 8).
- A real implementation can be substituted behind any of these interfaces without
  touching the caller.
- Every provider's contract is schema-validated before use (`ProviderContractError` in
  P1; Pydantic validation everywhere else) — a malformed provider response is never
  silently trusted (CLAUDE.md rule 12).
- The two provider interfaces added in P10 (`ExternalIdentityVerificationProvider`,
  `ExternalFraudSignalProvider`) are deliberately *not* wired into any decision path —
  see ADR-006-style reasoning in `docs/architecture/overview.md`: introducing a new
  evidence source that could change a decision is a policy change, not an architecture
  change.
