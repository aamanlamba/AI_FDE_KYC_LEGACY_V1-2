"""Retry/timeout helpers for external provider adapters (P10 requirement 10: retries
where justified, timeouts for external adapters).

This repository's own deterministic offline providers (DeterministicSidecarProvider,
DeterministicMarkerForensicsProvider, DeterministicReviewSummaryProvider,
StaticWorkshopAuthorizer) never need this: they are synchronous, in-process, and
either succeed or raise deterministically -- there is nothing to retry or time out.
This module exists for the external provider interfaces in this package, and for
whatever real network-backed adapter a deployment implements against them.
"""

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class ProviderTimeoutError(RuntimeError):
    """Raised by a real adapter when an external call exceeds its configured timeout.
    Not raised by anything in this repository today (nothing here makes a network
    call) -- defined so a real adapter has a single, catchable exception type to use."""


class ProviderUnavailableError(RuntimeError):
    """Raised by call_with_retries once every attempt has failed."""


def call_with_retries(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 0.1,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """A small, deterministic, linear-backoff retry loop. max_attempts=1 disables
    retrying entirely (useful for a call that is known not to be safely retryable,
    e.g. one with a side effect that is not idempotent). Raises
    ProviderUnavailableError, chained from the last underlying exception, once every
    attempt is exhausted -- callers see one exception type regardless of how many
    attempts were made or what the underlying provider raised.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    raise ProviderUnavailableError(f"exhausted {max_attempts} attempt(s)") from last_exc
