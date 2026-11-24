"""Resilience primitives for upstream calls: a circuit breaker and retry-with-backoff.

Kept dependency-free (no tenacity/pybreaker) so the behaviour is explicit, unit-testable
with an injected clock/sleep, and easy to reason about in a review."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

log = logging.getLogger("support_platform.resilience")
T = TypeVar("T")


class UpstreamErrorKind(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    CIRCUIT_OPEN = "circuit_open"
    BAD_RESPONSE = "bad_response"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class UpstreamError(Exception):
    def __init__(self, source: str, kind: UpstreamErrorKind, detail: str = "", status: int | None = None,
                 payload: dict | None = None) -> None:
        super().__init__(f"{source}: {kind} {detail}".strip())
        self.source = source
        self.kind = kind
        self.status = status
        self.payload = payload or {}

    @property
    def retryable(self) -> bool:
        return self.kind in (UpstreamErrorKind.TIMEOUT, UpstreamErrorKind.UNAVAILABLE)

    @property
    def counts_as_failure(self) -> bool:
        """Client-side errors (404/409/412/422) say nothing about upstream health."""
        return self.kind in (UpstreamErrorKind.TIMEOUT, UpstreamErrorKind.UNAVAILABLE,
                             UpstreamErrorKind.BAD_RESPONSE)


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Classic three-state breaker.

    CLOSED  --(failure_threshold consecutive failures)--> OPEN
    OPEN    --(reset_timeout elapsed)--> HALF_OPEN (one trial call allowed)
    HALF_OPEN --success--> CLOSED ; --failure--> OPEN
    """

    def __init__(self, name: str, failure_threshold: int = 5, reset_timeout_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN and self._clock() - self._opened_at >= self.reset_timeout_s:
            return BreakerState.HALF_OPEN
        return self._state

    def before_call(self) -> None:
        state = self.state
        if state is BreakerState.OPEN:
            raise UpstreamError(self.name, UpstreamErrorKind.CIRCUIT_OPEN, "circuit open")
        if state is BreakerState.HALF_OPEN:
            if self._trial_in_flight:
                raise UpstreamError(self.name, UpstreamErrorKind.CIRCUIT_OPEN, "half-open trial in flight")
            self._state = BreakerState.HALF_OPEN
            self._trial_in_flight = True

    def record_success(self) -> None:
        if self._state is not BreakerState.CLOSED:
            log.info("circuit closed", extra={"upstream": self.name})
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._trial_in_flight = False

    def record_failure(self) -> None:
        self._trial_in_flight = False
        if self._state is BreakerState.HALF_OPEN:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._trip()

    def release_trial(self) -> None:
        """Call outcome was neutral (e.g. a 404): don't hold the half-open slot."""
        if self._state is BreakerState.HALF_OPEN:
            self._trial_in_flight = False

    def _trip(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        log.warning("circuit opened", extra={"upstream": self.name, "failures": self._failures})


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_s: float = 0.1
    max_delay_s: float = 1.0

    def backoff(self, attempt: int) -> float:
        """Exponential backoff with full jitter (AWS architecture blog)."""
        cap = min(self.max_delay_s, self.base_delay_s * (2 ** attempt))
        return random.uniform(0, cap)


async def call_with_resilience(
    breaker: CircuitBreaker,
    policy: RetryPolicy,
    fn: Callable[[], Awaitable[T]],
    *,
    retry: bool,
    deadline_s: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run ``fn`` through the breaker, retrying retryable failures within an overall deadline.

    Non-idempotent operations must pass ``retry=False`` unless the upstream accepts an
    idempotency key (comments do; we forward ours)."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    attempts = policy.attempts if retry else 1
    last: UpstreamError | None = None
    for attempt in range(attempts):
        breaker.before_call()
        try:
            result = await fn()
        except UpstreamError as exc:
            last = exc
            if exc.counts_as_failure:
                breaker.record_failure()
            else:
                breaker.release_trial()
                raise
            if not exc.retryable or attempt == attempts - 1:
                raise
            delay = policy.backoff(attempt)
            if loop.time() - started + delay >= deadline_s:
                raise
            log.info("retrying upstream call", extra={"upstream": breaker.name, "attempt": attempt + 1,
                                                      "delay_s": round(delay, 3), "error": exc.kind})
            await sleep(delay)
            continue
        breaker.record_success()
        return result
    assert last is not None  # pragma: no cover
    raise last
