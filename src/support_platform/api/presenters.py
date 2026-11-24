"""Domain -> wire representations, including field-level authorization.

Field-level rules live here and only here:
  * ``contract.arrUsd``      requires ``finance:read``
  * ``primaryContact``       requires ``pii:read``
Withheld fields are *omitted* (not nulled) and listed in ``redactedFields`` so a client
can tell "you may not see this" apart from "this is empty"."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from support_platform.domain.models import Account, Case, Comment
from support_platform.security.auth import FINANCE_READ, PII_READ, Principal
from support_platform.services.customers import CustomerView, case_counts


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def account_ref(a: Account) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "supportTier": a.support_tier.value, "renewalDate": a.contract_end.isoformat()}


def case_summary(c: Case, now: datetime, account: Account | None = None, include_account: bool = False) -> dict:
    out: dict[str, Any] = {
        "id": c.id,
        "accountId": c.account_id,
        "priority": c.priority.value,
        "status": c.status.value,
        "subject": c.subject,
        "openedAt": _ts(c.opened_at),
        "updatedAt": _ts(c.updated_at),
        "ageHours": round((now - c.opened_at).total_seconds() / 3600, 1),
        "escalationLevel": c.escalation.level,
        "commentCount": c.comment_count,
    }
    if include_account:
        out["account"] = account_ref(account) if account else None
    return out


def comment(c: Comment) -> dict[str, Any]:
    return {"id": c.id, "author": c.author, "body": c.body, "createdAt": _ts(c.created_at),
            "visibility": c.visibility.value}


def case_detail(c: Case, now: datetime) -> dict[str, Any]:
    out = case_summary(c, now)
    out["escalation"] = {"level": c.escalation.level, "targetTeam": c.escalation.target_team,
                         "reason": c.escalation.reason}
    out["comments"] = [comment(x) for x in (c.comments or [])]
    out["commentCount"] = len(out["comments"])
    return out


def customer_summary(view: CustomerView, principal: Principal, now: datetime) -> dict[str, Any]:
    a = view.account
    redacted: list[str] = []
    contract: dict[str, Any] = {"endDate": a.contract_end.isoformat(),
                                "renewalInDays": (a.contract_end - now.date()).days}
    if principal.has(FINANCE_READ):
        contract["arrUsd"] = a.arr_usd
    else:
        redacted.append("contract.arrUsd")

    out: dict[str, Any] = {"id": a.id, "name": a.name, "supportTier": a.support_tier.value, "contract": contract}
    if principal.has(PII_READ):
        out["primaryContact"] = {"email": a.primary_contact_email}
    else:
        redacted.append("primaryContact")

    if view.usage is not None:
        hist = sorted(view.usage, key=lambda u: u.month)
        latest = hist[-1] if hist else None
        trend = "flat"
        if len(hist) >= 2 and hist[0].protected_tb:
            delta = (hist[-1].protected_tb - hist[0].protected_tb) / hist[0].protected_tb
            trend = "up" if delta > 0.05 else "down" if delta < -0.05 else "flat"
        out["usage"] = {
            "latestMonth": latest.month if latest else None,
            "protectedTb": latest.protected_tb if latest else None,
            "apiCalls": latest.api_calls if latest else None,
            "activeUsers": latest.active_users if latest else None,
            "protectedTbTrend": trend,
            "history": [{"month": u.month, "protectedTb": u.protected_tb, "apiCalls": u.api_calls,
                         "activeUsers": u.active_users} for u in hist],
        }
    else:
        out["usage"] = None
    out["cases"] = case_counts(view.active_cases) if view.active_cases is not None else None
    out["degraded"] = view.degraded
    out["dataSources"] = [
        {k: v for k, v in {"source": s.source, "status": s.status, "asOf": _ts(s.as_of) if s.as_of else None,
                           "reason": s.reason}.items() if v is not None}
        for s in view.sources
    ]
    out["redactedFields"] = redacted
    return out
