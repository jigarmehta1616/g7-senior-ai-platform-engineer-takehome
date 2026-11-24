import pytest

from support_platform.upstreams.resilience import (
    BreakerState,
    CircuitBreaker,
    RetryPolicy,
    UpstreamError,
    UpstreamErrorKind,
    call_with_resilience,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def _no_sleep(_: float) -> None:
    return None


def _failing(kind: UpstreamErrorKind, calls: list[int]):
    async def fn():
        calls.append(1)
        raise UpstreamError("usage", kind)
    return fn


def test_breaker_opens_after_threshold_and_half_opens_after_timeout():
    clock = FakeClock()
    b = CircuitBreaker("usage", failure_threshold=2, reset_timeout_s=10, clock=clock)
    b.before_call()
    b.record_failure()
    assert b.state is BreakerState.CLOSED
    b.before_call()
    b.record_failure()
    assert b.state is BreakerState.OPEN
    with pytest.raises(UpstreamError) as ei:
        b.before_call()
    assert ei.value.kind is UpstreamErrorKind.CIRCUIT_OPEN

    clock.now = 10
    assert b.state is BreakerState.HALF_OPEN
    b.before_call()                       # the single trial call
    with pytest.raises(UpstreamError):    # a second concurrent call is rejected
        b.before_call()
    b.record_success()
    assert b.state is BreakerState.CLOSED


def test_half_open_failure_reopens():
    clock = FakeClock()
    b = CircuitBreaker("cases", failure_threshold=1, reset_timeout_s=5, clock=clock)
    b.before_call()
    b.record_failure()
    clock.now = 5
    b.before_call()
    b.record_failure()
    assert b.state is BreakerState.OPEN


@pytest.mark.anyio
async def test_retries_retryable_errors_then_gives_up():
    calls: list[int] = []
    b = CircuitBreaker("usage", failure_threshold=10)
    with pytest.raises(UpstreamError):
        await call_with_resilience(b, RetryPolicy(attempts=3), _failing(UpstreamErrorKind.UNAVAILABLE, calls),
                                   retry=True, deadline_s=5, sleep=_no_sleep)
    assert len(calls) == 3


@pytest.mark.anyio
async def test_does_not_retry_non_idempotent_or_client_errors():
    b = CircuitBreaker("cases", failure_threshold=10)
    calls: list[int] = []
    with pytest.raises(UpstreamError):
        await call_with_resilience(b, RetryPolicy(attempts=3), _failing(UpstreamErrorKind.UNAVAILABLE, calls),
                                   retry=False, deadline_s=5, sleep=_no_sleep)
    assert len(calls) == 1

    calls.clear()
    with pytest.raises(UpstreamError):
        await call_with_resilience(b, RetryPolicy(attempts=3), _failing(UpstreamErrorKind.NOT_FOUND, calls),
                                   retry=True, deadline_s=5, sleep=_no_sleep)
    assert len(calls) == 1
    assert b.state is BreakerState.CLOSED  # 404s say nothing about upstream health


@pytest.mark.anyio
async def test_recovers_when_a_retry_succeeds():
    attempts = {"n": 0}
    b = CircuitBreaker("usage", failure_threshold=10)

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise UpstreamError("usage", UpstreamErrorKind.TIMEOUT)
        return "ok"

    assert await call_with_resilience(b, RetryPolicy(attempts=3), flaky, retry=True, deadline_s=5,
                                      sleep=_no_sleep) == "ok"


def test_backoff_is_bounded_full_jitter():
    p = RetryPolicy(attempts=5, base_delay_s=0.1, max_delay_s=0.5)
    for attempt in range(6):
        assert 0 <= p.backoff(attempt) <= 0.5

