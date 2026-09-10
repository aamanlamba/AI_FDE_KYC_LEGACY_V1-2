"""A small, in-memory idempotency cache for mutating endpoints (P10 requirement 10).

Same scope caveat as RateLimiter (src.security.limits): single-process, in-memory,
appropriate for a locally-runnable workshop service. A real deployment would back this
with a shared store (e.g. Redis with a TTL) behind the same get()/put() interface.

Without this, a client that retries a POST /v1/reviews/{id}/transitions request (e.g.
after a network timeout, unsure whether the first attempt was applied) risks either a
duplicate audit-log entry or a confusing 409 InvalidTransitionError on the retry, even
though the original request succeeded. With an Idempotency-Key header, a retried
request with the same key returns the original response instead of re-attempting the
transition.
"""

import threading
import time
from typing import Any


class IdempotencyCache:
    def __init__(self, ttl_seconds: float = 300.0):
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at > self._ttl_seconds:
                del self._entries[key]
                return None
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), value)

    def get_or_compute(self, key: str, compute) -> Any:
        """Atomically check-and-populate for one key.

        P11 red-team finding: separate get()/put() calls around a mutating operation
        (as app.py originally did) leave a window between another caller's compute
        succeeding and its put() landing, in which a concurrent retry with the same key
        re-runs compute() itself and can observe a now-invalid state (e.g. a 409 on a
        transition that already happened), defeating the point of the idempotency key.
        Holding the lock for the whole check-compute-store sequence serializes retries
        of the same key so only one ever actually executes `compute`. A failed compute
        is not cached, matching the previous get()/put() behavior.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                stored_at, value = entry
                if time.monotonic() - stored_at <= self._ttl_seconds:
                    return value
                del self._entries[key]
            value = compute()
            self._entries[key] = (time.monotonic(), value)
            return value

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


review_transition_idempotency_cache = IdempotencyCache()
