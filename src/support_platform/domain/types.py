"""Shared type aliases and small value types used across layers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from support_platform.domain.models import Account

Clock = Callable[[], datetime]
"""Returns the current UTC time. Injected everywhere so tests can freeze time."""

JSONDict = dict[str, Any]
"""A JSON object as produced by the presenters / consumed from upstream payloads."""

SourceName = Literal["entitlements", "usage", "cases"]
SourceState = Literal["ok", "stale", "unavailable"]
AuditOutcome = Literal["success", "denied", "failed"]


@dataclass(frozen=True)
class AccountResult:
    """An account plus where it came from: live REST call, or the CSV/XML snapshot (stale)."""

    account: Account
    stale: bool
    as_of: datetime
