"""Adapter for the usage warehouse (Snowflake-like SQL statements API).

The statement is a constant; customer input only ever travels as a bind variable, so
there is no SQL-injection surface even though the upstream speaks SQL."""

from __future__ import annotations

from support_platform.domain.models import UsageMonth
from support_platform.upstreams.http import UpstreamHttp, _json
from support_platform.upstreams.resilience import UpstreamError, UpstreamErrorKind
from support_platform.upstreams.translators import usage_from_sql_result

_USAGE_SQL = (
    "SELECT account_id, month, protected_tb, api_calls, active_users "
    "FROM usage_monthly WHERE account_id = ? ORDER BY month DESC LIMIT ?"
)


class UsageClient:
    def __init__(self, http: UpstreamHttp) -> None:
        self.http = http

    async def monthly_usage(self, account_id: str, months: int = 3) -> list[UsageMonth]:
        # Read-only statement: safe to retry.
        resp = await self.http.request(
            "POST", "/usage/api/v2/statements", retry=True,
            json={"statement": _USAGE_SQL,
                  "bindings": {"1": {"type": "TEXT", "value": account_id},
                               "2": {"type": "FIXED", "value": months}}},
        )
        try:
            return usage_from_sql_result(_json("usage", resp))
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamError("usage", UpstreamErrorKind.BAD_RESPONSE, str(exc)) from exc
