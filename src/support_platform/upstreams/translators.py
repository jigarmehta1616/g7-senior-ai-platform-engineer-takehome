"""Anti-corruption layer: the only place that knows upstream field names and formats.

* Case system: inconsistent casing (``Status`` vs ``status``, ``Comments``), int versions.
* Entitlement system: CSV export (snake_case, numbers as strings) + XML change feed whose
  ``<tier>``/``<renewal>`` override the CSV.
* Usage warehouse: Snowflake SQL API returns every value as a string.

Account IDs are treated as opaque strings. The appendix shows both ``ACC-77`` and
``ACC-007``; normalising (zero-padding) could silently merge two customers' data, so we
don't guess."""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

from support_platform.domain.models import (
    Account,
    Case,
    CaseStatus,
    Comment,
    CommentVisibility,
    Escalation,
    Priority,
    SupportTier,
    UsageMonth,
)

_STATUS_ALIASES = {
    "open": CaseStatus.OPEN, "new": CaseStatus.OPEN,
    "in progress": CaseStatus.IN_PROGRESS, "in_progress": CaseStatus.IN_PROGRESS, "working": CaseStatus.IN_PROGRESS,
    "pending_customer": CaseStatus.PENDING_CUSTOMER, "waiting on customer": CaseStatus.PENDING_CUSTOMER,
    "resolved": CaseStatus.RESOLVED, "closed": CaseStatus.CLOSED,
}


class TranslationError(ValueError):
    pass


def _ci(d: dict[str, Any], key: str, default: Any = None) -> Any:
    """Case-insensitive key lookup."""
    if key in d:
        return d[key]
    lower = key.lower()
    for k, v in d.items():
        if k.lower() == lower:
            return v
    return default


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def status_from_upstream(raw: str) -> CaseStatus:
    try:
        return _STATUS_ALIASES[raw.strip().lower()]
    except KeyError as exc:
        raise TranslationError(f"unknown case status {raw!r}") from exc


def status_to_upstream(status: CaseStatus) -> str:
    return status.value


def case_from_upstream(raw: dict[str, Any]) -> Case:
    try:
        comments_raw = _ci(raw, "Comments")
        comments = None
        if comments_raw is not None:
            comments = [
                Comment(
                    id=str(c.get("id") or f"{raw['id']}-c{i}"),
                    author=str(c.get("author", "unknown")),
                    body=str(c.get("body", "")),
                    created_at=_dt(c["at"]),
                    visibility=CommentVisibility(c.get("visibility", "internal")),
                )
                for i, c in enumerate(comments_raw)
            ]
        opened = _dt(_ci(raw, "openedAt"))
        return Case(
            id=raw["id"],
            account_id=_ci(raw, "accountId"),
            priority=Priority(_ci(raw, "priority")),
            status=status_from_upstream(_ci(raw, "Status")),
            subject=_ci(raw, "subject", ""),
            opened_at=opened,
            updated_at=_dt(_ci(raw, "updatedAt")) if _ci(raw, "updatedAt") else opened,
            version=int(_ci(raw, "version", 1)),
            escalation=Escalation(
                level=int(_ci(raw, "escalationLevel", 0) or 0),
                target_team=_ci(raw, "escalatedTo"),
                reason=_ci(raw, "escalationReason"),
            ),
            comment_count=int(_ci(raw, "commentCount", len(comments) if comments is not None else 0)),
            comments=comments,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TranslationError(f"cannot translate case payload: {exc}") from exc


def account_from_upstream(raw: dict[str, Any]) -> Account:
    try:
        arr = raw.get("arr_usd")
        return Account(
            id=raw["account_id"],
            name=raw["name"],
            support_tier=SupportTier(raw["support_tier"]),
            contract_end=date.fromisoformat(raw["contract_end"]),
            arr_usd=int(float(arr)) if arr not in (None, "") else None,
            primary_contact_email=raw.get("primary_contact_email") or None,
        )
    except (KeyError, ValueError) as exc:
        raise TranslationError(f"cannot translate account payload: {exc}") from exc


def accounts_from_csv(text: str) -> dict[str, Account]:
    return {a.id: a for a in (account_from_upstream(row) for row in csv.DictReader(io.StringIO(text)))}


def apply_xml_feed(accounts: dict[str, Account], xml_text: str) -> dict[str, Account]:
    """XML change feed wins over the nightly CSV for tier and renewal date."""
    root = ET.fromstring(xml_text)  # noqa: S314 - upstream is an internal system; see SECURITY.md (defusedxml in prod)
    out = dict(accounts)
    for node in root.iter("account"):
        acc_id = node.get("id")
        if not acc_id or acc_id not in out:
            continue
        updates: dict[str, Any] = {}
        if tier := node.findtext("tier"):
            updates["support_tier"] = SupportTier(tier.strip())
        if renewal := node.findtext("renewal"):
            updates["contract_end"] = date.fromisoformat(renewal.strip())
        out[acc_id] = out[acc_id].model_copy(update=updates)
    return out


def usage_from_sql_result(result: dict[str, Any]) -> list[UsageMonth]:
    cols = [c["name"].lower() for c in result["resultSetMetaData"]["rowType"]]
    rows = []
    for values in result.get("data", []):
        rec = dict(zip(cols, values, strict=True))
        rows.append(UsageMonth(
            month=rec["month"],
            protected_tb=float(rec["protected_tb"]),
            api_calls=int(rec["api_calls"]),
            active_users=int(rec["active_users"]),
        ))
    return rows
