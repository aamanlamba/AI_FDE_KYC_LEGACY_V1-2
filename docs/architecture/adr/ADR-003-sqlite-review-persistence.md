# ADR-003: SQLite, single-connection-with-lock, for review persistence

**Status**: Accepted (P6), interface formalized (P10)

## Context
P6 needed the first durable persistence in this repository (the HITL review
workflow). Options considered: an external database (Postgres, etc.), an in-memory
structure with no durability, or an embedded file-based database.

## Decision
SQLite via the stdlib `sqlite3` module, with one persistent connection per
`ReviewStore` instance guarded by a `threading.Lock`. In P10, formalized behind a
`ReviewRepository` abstract interface (see ADR-001) without renaming or moving the
concrete class.

## Consequences
- Zero new runtime dependencies, zero external services — consistent with "runs fully
  offline" and "no unnecessary services" (CLAUDE.md rule 7, P8/P10 requirements).
- A single lock-guarded connection serializes all review-store access. This is a
  throughput ceiling under heavy *review-mutation* load specifically, not for the
  stateless verify endpoints that carry the overwhelming majority of expected traffic
  — judged acceptable for this workshop's scale and explicitly documented as a
  single-process limitation in `docs/architecture/overview.md`'s concurrency section.
- `":memory:"` databases require exactly this pattern (one held-open connection) --
  discovered as a real bug during P6 testing (an earlier per-call-connection design
  silently created a fresh empty `:memory:` database on every call) and is now
  load-bearing for both the workshop default and every in-memory test fixture.
- A real deployment can implement `ReviewRepository` against Postgres/DynamoDB/etc.
  without any caller (`src/app.py`, `src/review/workflow.py`) changing, since they
  depend on `ReviewStore` only through the methods `ReviewRepository` declares.
