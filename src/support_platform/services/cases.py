"""Case search, comments and escalation."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from support_platform.domain import errors
from support_platform.domain.cursor import CursorCodec, filters_hash
from support_platform.domain.escalation import plan_escalation
from support_platform.domain.interfaces import CaseSystemPort, EntitlementPort, EventPublisherPort
from support_platform.domain.models import (
    Account,
    Case,
    CaseStatus,
    Comment,
    CommentCreate,
    EscalateRequest,
    Priority,
    SupportTier,
)
from support_platform.domain.types import Clock
from support_platform.security.auth import Principal
from support_platform.services.customers import upstream_to_problem
from support_platform.upstreams.resilience import UpstreamError, UpstreamErrorKind

_PRIORITY_RANK = {Priority.P1: 1, Priority.P2: 2, Priority.P3: 3}


class CaseSort(StrEnum):
    OPENED_ASC = "openedAt"
    OPENED_DESC = "-openedAt"
    PRIORITY_ASC = "priority"      # P1 first
    PRIORITY_DESC = "-priority"    # P3 first


@dataclass(frozen=True)
class CaseQuery:
    statuses: tuple[CaseStatus, ...] = ()
    priorities: tuple[Priority, ...] = ()
    account_id: str | None = None
    support_tier: SupportTier | None = None
    renewal_before: date | None = None
    opened_before: datetime | None = None
    opened_after: datetime | None = None
    sort: CaseSort = CaseSort.OPENED_DESC
    limit: int = 25
    cursor: str | None = None
    include_account: bool = False

    def filter_fingerprint(self) -> str:
        return filters_hash({
            "s": sorted(self.statuses), "p": sorted(self.priorities), "a": self.account_id,
            "t": self.support_tier, "r": self.renewal_before, "ob": self.opened_before, "oa": self.opened_after,
            "o": self.sort.value, "i": self.include_account,
        })


@dataclass
class CasePage:
    items: list[Case]
    accounts: dict[str, Account]
    next_cursor: str | None
    stale_sources: list[str]


def _sort_key(case: Case, sort: CaseSort) -> list[Any]:
    if sort in (CaseSort.PRIORITY_ASC, CaseSort.PRIORITY_DESC):
        return [_PRIORITY_RANK[case.priority], case.opened_at.isoformat(), case.id]
    return [case.opened_at.isoformat(), case.id]


class CaseService:
    def __init__(self, cases: CaseSystemPort, entitlements: EntitlementPort, outbox: EventPublisherPort,
                 cursors: CursorCodec, clock: Clock) -> None:
        self._cases = cases
        self._ent = entitlements
        self._outbox = outbox
        self._cursors = cursors
        self._clock = clock

    # ---- search ---------------------------------------------------------------------
    async def search(self, q: CaseQuery) -> CasePage:
        fhash = q.filter_fingerprint()
        after = self._cursors.decode(q.cursor, fhash) if q.cursor else None

        accounts: dict[str, Account] = {}
        stale: list[str] = []
        needs_accounts = q.support_tier is not None or q.renewal_before is not None

        # The two upstream calls are independent, so run them concurrently: in an outage the
        # caller waits for one deadline, not the sum of both.
        cases_call = self._cases.list_cases(account_id=q.account_id, statuses=list(q.statuses) or None,
                                            priorities=list(q.priorities) or None)
        if needs_accounts or q.include_account:
            acc_res, cases_res = await asyncio.gather(self._ent.list_accounts(), cases_call, return_exceptions=True)
        else:
            acc_res, cases_res = None, (await asyncio.gather(cases_call, return_exceptions=True))[0]

        if isinstance(acc_res, UpstreamError):
            if needs_accounts:   # can't evaluate the filter honestly -> fail, don't guess
                raise upstream_to_problem(acc_res) from acc_res
            stale.append("entitlements")
        elif isinstance(acc_res, BaseException):
            raise acc_res
        elif acc_res is not None:
            acc_list, is_stale = acc_res
            accounts = {a.id: a for a in acc_list}
            if is_stale:
                stale.append("entitlements")

        if isinstance(cases_res, UpstreamError):
            raise upstream_to_problem(cases_res) from cases_res
        if isinstance(cases_res, BaseException):
            raise cases_res
        raw = cases_res

        allowed_accounts: set[str] | None = None
        if needs_accounts:
            allowed_accounts = {
                a.id for a in accounts.values()
                if (q.support_tier is None or a.support_tier is q.support_tier)
                and (q.renewal_before is None or a.contract_end <= q.renewal_before)
            }

        rows = [
            c for c in raw
            if (allowed_accounts is None or c.account_id in allowed_accounts)
            and (q.opened_before is None or c.opened_at < q.opened_before)
            and (q.opened_after is None or c.opened_at >= q.opened_after)
        ]
        descending = q.sort in (CaseSort.OPENED_DESC, CaseSort.PRIORITY_DESC)
        rows.sort(key=lambda c: _sort_key(c, q.sort), reverse=descending)
        if after is not None:
            rows = [c for c in rows if (_sort_key(c, q.sort) < after if descending else _sort_key(c, q.sort) > after)]
        page = rows[: q.limit]
        next_cursor = (self._cursors.encode(_sort_key(page[-1], q.sort), fhash)
                       if len(rows) > q.limit and page else None)
        return CasePage(items=page, accounts=accounts, next_cursor=next_cursor, stale_sources=stale)

    async def get(self, case_id: str) -> Case:
        try:
            return await self._cases.get_case(case_id)
        except UpstreamError as exc:
            if exc.kind is UpstreamErrorKind.NOT_FOUND:
                raise errors.not_found("Case", case_id) from exc
            raise upstream_to_problem(exc) from exc

    # ---- comments -------------------------------------------------------------------
    async def add_comment(self, case_id: str, body: CommentCreate, principal: Principal,
                          idempotency_key: str) -> Comment:
        await self.get(case_id)   # 404 before write; also validates the case exists for audit
        # Forward a key derived from (principal, client key) so the upstream de-dupes our
        # retries without different callers' keys ever colliding.
        upstream_key = hashlib.sha256(f"{principal.subject}|{idempotency_key}".encode()).hexdigest()[:32]
        author = principal.subject if not principal.actor else f"{principal.subject} via {principal.actor}"
        try:
            return await self._cases.add_comment(case_id, author=author, body=body.body,
                                                 visibility=body.visibility, idempotency_key=upstream_key)
        except UpstreamError as exc:
            if exc.kind is UpstreamErrorKind.NOT_FOUND:
                raise errors.not_found("Case", case_id) from exc
            raise upstream_to_problem(exc) from exc

    # ---- escalation -----------------------------------------------------------------
    async def escalate(self, case_id: str, req: EscalateRequest, principal: Principal,
                       if_match: str | None) -> Case:
        if not if_match:
            raise errors.precondition_required()
        case = await self.get(case_id)
        if if_match.strip() not in (case.etag, f"W/{case.etag}"):
            raise errors.etag_mismatch(case.etag)
        try:
            ent = await self._ent.get_account(case.account_id)
        except UpstreamError as exc:
            raise upstream_to_problem(exc) from exc
        plan = plan_escalation(case, ent.account.support_tier, req.reason, req.note)
        try:
            updated = await self._cases.apply_escalation(case_id, expected_version=case.version,
                                                         level=plan.new_level, target_team=plan.target_team,
                                                         reason=req.reason.value)
        except UpstreamError as exc:
            if exc.kind is UpstreamErrorKind.CONFLICT:
                current = exc.payload.get("currentVersion")
                raise errors.etag_mismatch(f'"v{current}"' if current else case.etag) from exc
            raise upstream_to_problem(exc) from exc

        self._outbox.enqueue("case.escalated", source=f"/v1/cases/{case_id}", data={
            "caseId": updated.id,
            "accountId": updated.account_id,
            "priority": updated.priority.value,
            "status": updated.status.value,
            "escalationLevel": plan.new_level,
            "targetTeam": plan.target_team,
            "reason": req.reason.value,
            "escalatedBy": {"subject": principal.subject, "agent": principal.actor},
        })
        return updated
