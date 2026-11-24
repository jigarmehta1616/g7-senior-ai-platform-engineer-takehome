"""Token-bucket rate limiter keyed by (user, agent). Agents get a tighter budget than
humans because a looping agent can burn through quota in seconds. In-memory is fine for
one replica; multi-replica deployments move this to the gateway or Redis (DECISIONS.md)."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_s: int


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def check(self, key: str, per_minute: int) -> RateDecision:
        rate = per_minute / 60.0
        now = self._clock()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = self._buckets[key] = _Bucket(tokens=float(per_minute), updated=now)
            b.tokens = min(per_minute, b.tokens + (now - b.updated) * rate)
            b.updated = now
            if b.tokens >= 1:
                b.tokens -= 1
                reset = math.ceil((per_minute - b.tokens) / rate)
                return RateDecision(True, per_minute, int(b.tokens), reset)
            wait = math.ceil((1 - b.tokens) / rate)
            return RateDecision(False, per_minute, 0, max(wait, 1))
