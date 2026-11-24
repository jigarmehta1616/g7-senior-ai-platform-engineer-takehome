"""Types and interfaces for the Support Copilot MCP server."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Protocol

import mcp.types as t

ToolClass = Literal["read", "write", "escalate"]
"""Rate-limit bucket a tool belongs to."""

ToolBody = Callable[[str], Awaitable[t.CallToolResult]]
"""A tool's implementation; receives the call's correlation ID."""

Clock = Callable[[], datetime]

PriorityLit = Literal["P1", "P2", "P3"]
StatusLit = Literal["open", "in_progress", "pending_customer", "resolved", "closed"]
TierLit = Literal["Platinum", "Gold", "Silver", "Standard"]
ReasonLit = Literal["customer_impact", "sla_breach_risk", "security_incident", "executive_request", "other"]
SortLit = Literal["oldest_first", "newest_first", "priority"]
VisibilityLit = Literal["internal", "public"]


class ApiResultLike(Protocol):
    status: int
    body: Any
    headers: dict[str, str]

    @property
    def ok(self) -> bool: ...

    def problem_summary(self) -> dict[str, Any]: ...


class PlatformApiPort(Protocol):
    """What the tools need from the platform API. ``api_client.PlatformApi`` implements it."""

    async def search_cases(self, params: dict[str, Any], *, cid: str) -> ApiResultLike: ...

    async def get_case(self, case_id: str, *, cid: str, tool: str) -> ApiResultLike: ...

    async def get_customer(self, customer_id: str, *, cid: str) -> ApiResultLike: ...

    async def add_comment(self, case_id: str, body: str, visibility: str, idempotency_key: str, *,
                          cid: str) -> ApiResultLike: ...

    async def escalate(self, case_id: str, reason: str, note: str | None, etag: str, *,
                       cid: str) -> ApiResultLike: ...

    async def aclose(self) -> None: ...
