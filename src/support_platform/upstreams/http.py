"""Thin HTTP wrapper shared by all upstream adapters: per-attempt timeout, error
classification, correlation-ID propagation, then breaker + retry via ``resilience``."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from support_platform.observability.logging import correlation_id_var
from support_platform.upstreams.resilience import (
    CircuitBreaker,
    RetryPolicy,
    UpstreamError,
    UpstreamErrorKind,
    call_with_resilience,
)


class UpstreamHttp:
    def __init__(self, name: str, client: httpx.AsyncClient, base_url: str, *, timeout_s: float,
                 deadline_s: float, breaker: CircuitBreaker, policy: RetryPolicy) -> None:
        self.name = name
        self._client = client
        self._base = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._deadline_s = deadline_s
        self.breaker = breaker
        self._policy = policy

    async def request(self, method: str, path: str, *, retry: bool, params: dict[str, Any] | None = None,
                      json: Any = None, headers: dict[str, str] | None = None) -> httpx.Response:
        hdrs = {"X-Correlation-ID": correlation_id_var.get()}
        hdrs.update(headers or {})

        async def attempt() -> httpx.Response:
            try:
                # asyncio.wait_for enforces the per-attempt budget regardless of transport
                # (httpx timeouts don't apply to in-process ASGI transports used in tests).
                resp = await asyncio.wait_for(
                    self._client.request(method, self._base + path, params=params, json=json, headers=hdrs,
                                         timeout=self._timeout_s),
                    timeout=self._timeout_s,
                )
            except (TimeoutError, httpx.TimeoutException) as exc:
                raise UpstreamError(self.name, UpstreamErrorKind.TIMEOUT, "timed out") from exc
            except httpx.TransportError as exc:
                raise UpstreamError(self.name, UpstreamErrorKind.UNAVAILABLE, type(exc).__name__) from exc
            return _classify(self.name, resp)

        return await call_with_resilience(self.breaker, self._policy, attempt, retry=retry,
                                          deadline_s=self._deadline_s)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self.request("GET", path, retry=True, params=params)
        return _json(self.name, resp)

    async def get_text(self, path: str) -> str:
        resp = await self.request("GET", path, retry=True)
        return resp.text


def _json(source: str, resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise UpstreamError(source, UpstreamErrorKind.BAD_RESPONSE, "non-JSON body") from exc


def _classify(source: str, resp: httpx.Response) -> httpx.Response:
    code = resp.status_code
    if code < 400:
        return resp
    payload: dict[str, Any] = {}
    try:
        body = resp.json()
        payload = body if isinstance(body, dict) else {}
    except ValueError:
        pass
    if code == 404:
        raise UpstreamError(source, UpstreamErrorKind.NOT_FOUND, status=code, payload=payload)
    if code in (409, 412):
        raise UpstreamError(source, UpstreamErrorKind.CONFLICT, status=code, payload=payload)
    if code in (429, 502, 503, 504) or code >= 500:
        raise UpstreamError(source, UpstreamErrorKind.UNAVAILABLE, f"HTTP {code}", status=code)
    raise UpstreamError(source, UpstreamErrorKind.REJECTED, f"HTTP {code}", status=code, payload=payload)
