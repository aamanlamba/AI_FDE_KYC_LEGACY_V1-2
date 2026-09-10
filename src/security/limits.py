"""Resource bounds and a simple, testable rate-limit mechanism.

RateLimiter is an in-memory, single-process fixed-window counter -- appropriate for a
locally-runnable workshop service, explicitly not a distributed/production rate
limiter (a real deployment would back this with a shared store, e.g. Redis, behind the
same check() interface). It exists to give this repository a clearly testable
integration point (P8 requirement 11: "rate/resource-limit mechanisms or clearly
testable integration points"), not to claim production-grade throttling.
"""

import threading
import time

from .errors import RateLimitExceededError

# Resource bounds referenced by request models / handlers (kept here as the single
# source of truth so limits are visible in one place, not scattered across models).
MAX_RATIONALE_LENGTH = 2000
MAX_CORRECTION_LENGTH = 2000
MAX_ANALYST_ACTION_LENGTH = 200
MAX_IDENTIFIER_LENGTH = 80  # mirrors src.security.identifiers.MAX_IDENTIFIER_LENGTH


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        """Raises RateLimitExceededError if `key` has exceeded max_requests within the
        current window; otherwise records this call and returns."""
        now = time.monotonic()
        with self._lock:
            window_start = now - self._window_seconds
            recent = [t for t in self._hits.get(key, []) if t >= window_start]
            if len(recent) >= self._max_requests:
                self._hits[key] = recent
                raise RateLimitExceededError(
                    f"rate limit exceeded: {self._max_requests} requests per {self._window_seconds}s"
                )
            recent.append(now)
            self._hits[key] = recent

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Applied to review-mutation endpoints (the concrete demonstration point; see src/app.py).
review_transition_rate_limiter = RateLimiter(max_requests=20, window_seconds=60.0)
