"""HTTP client from the MCP server to the platform API.

The MCP server has **no credentials of its own**: it forwards the user's delegated token
(sub = user, act.sub = support-copilot). The API enforces scopes and field-level rules
exactly as for any other caller. Every request carries the tool call's correlation ID and
tool name so API audit rows join with the MCP audit log."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ApiResult:
    status: int
    body: Any
    headers: dict[str, str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def problem_summary(self) -> dict[str, Any]:
        b = self.body if isinstance(self.body, dict) else {}
        slug = str(b.get("type", "")).rsplit("/", 1)[-1] or "error"
        out = {"status": self.status, "type": slug, "detail": b.get("detail") or b.get("title") or "request failed"}
        for key in ("code", "upstream", "requiredScopes"):
            if key in b:
                out[key] = b[key]
        if "retry-after" in self.headers:
            out["retry_after_s"] = self.headers["retry-after"]
        return out


class PlatformApi:
    def __init__(self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=timeout_s,
                                         headers={"Authorization": f"Bearer {token}",
                                                  "User-Agent": "support-copilot-mcp/1.0"})

    async def _call(self, method: str, path: str, *, correlation_id: str, tool: str, params: dict | None = None,
                    json: Any = None, headers: dict[str, str] | None = None) -> ApiResult:
        hdrs = {"X-Correlation-ID": correlation_id, "X-Agent-Tool": tool, **(headers or {})}
        try:
            resp = await self._client.request(method, path, params=params, json=json, headers=hdrs)
        except httpx.HTTPError as exc:
            return ApiResult(503, {"type": "platform-unreachable", "detail": f"Platform API unreachable: "
                                   f"{type(exc).__name__}"}, {})
        try:
            body = resp.json() if resp.content else None
        except ValueError:
            body = {"detail": resp.text[:200]}
        return ApiResult(resp.status_code, body, {k.lower(): v for k, v in resp.headers.items()})

    async def search_cases(self, params: dict[str, Any], *, cid: str) -> ApiResult:
        return await self._call("GET", "/v1/cases", params=params, correlation_id=cid, tool="search_cases")

    async def get_case(self, case_id: str, *, cid: str, tool: str) -> ApiResult:
        return await self._call("GET", f"/v1/cases/{case_id}", correlation_id=cid, tool=tool)

    async def get_customer(self, customer_id: str, *, cid: str) -> ApiResult:
        return await self._call("GET", f"/v1/customers/{customer_id}", correlation_id=cid,
                                tool="get_customer_summary")

    async def add_comment(self, case_id: str, body: str, visibility: str, idempotency_key: str, *,
                          cid: str) -> ApiResult:
        return await self._call("POST", f"/v1/cases/{case_id}/comments", correlation_id=cid, tool="add_case_comment",
                                json={"body": body, "visibility": visibility},
                                headers={"Idempotency-Key": idempotency_key})

    async def escalate(self, case_id: str, reason: str, note: str | None, etag: str, *, cid: str) -> ApiResult:
        payload: dict[str, Any] = {"reason": reason}
        if note:
            payload["note"] = note
        return await self._call("POST", f"/v1/cases/{case_id}/escalate", correlation_id=cid, tool="escalate_case",
                                json=payload, headers={"If-Match": etag})

    async def aclose(self) -> None:
        await self._client.aclose()
