"""Ports (interfaces) the application services depend on.

Services are typed against these Protocols, not the concrete HTTP adapters, so an upstream can
be swapped (real Salesforce client, a cache, a fake in tests) without touching business logic.
The concrete adapters in ``support_platform.upstreams`` and ``support_platform.events``
satisfy them structurally; mypy checks that in CI."""

from __future__ import annotations

from typing import Any, Protocol

from support_platform.domain.models import (
    Account,
    Case,
    CaseStatus,
    Comment,
    CommentVisibility,
    Priority,
    UsageMonth,
)
from support_platform.domain.types import AccountResult


class CaseSystemPort(Protocol):
    """The system of record for cases and comments (Salesforce-like)."""

    async def list_cases(self, *, account_id: str | None = None, statuses: list[CaseStatus] | None = None,
                         priorities: list[Priority] | None = None) -> list[Case]: ...

    async def get_case(self, case_id: str) -> Case: ...

    async def add_comment(self, case_id: str, *, author: str, body: str, visibility: CommentVisibility,
                          idempotency_key: str) -> Comment: ...

    async def apply_escalation(self, case_id: str, *, expected_version: int, level: int, target_team: str,
                               reason: str) -> Case: ...


class EntitlementPort(Protocol):
    """Accounts, tiers, renewal dates and ARR (NetSuite-like)."""

    async def get_account(self, account_id: str) -> AccountResult: ...

    async def list_accounts(self) -> tuple[list[Account], bool]: ...

    async def refresh_snapshot(self) -> bool: ...


class UsagePort(Protocol):
    """Monthly product usage (Snowflake-like warehouse)."""

    async def monthly_usage(self, account_id: str, months: int = 3) -> list[UsageMonth]: ...


class EventPublisherPort(Protocol):
    """Where domain events go (transactional outbox locally; EventBridge/Kafka in production)."""

    def enqueue(self, event_type: str, *, source: str, data: dict[str, Any]) -> dict[str, Any]: ...
