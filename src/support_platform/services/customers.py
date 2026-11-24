"""Aggregated customer view: entitlement + usage + case counts, fetched concurrently.

Degradation policy (partial-failure handling):
  * entitlements - core. REST failure falls back to the CSV/XML snapshot (stale=True);
    no snapshot either -> 503 (we can't say who the customer *is*).
  * usage / cases - enrichment. Failure -> section is null, ``degraded=true`` and the
    failing source is named in ``dataSources`` so callers (and agents) can say so."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from support_platform.domain import errors
from support_platform.domain.interfaces import CaseSystemPort, EntitlementPort, UsagePort
from support_platform.domain.models import ACTIVE_STATUSES, Account, Case, Priority, UsageMonth
from support_platform.domain.types import Clock
from support_platform.upstreams.resilience import UpstreamError, UpstreamErrorKind


@dataclass
class SourceStatus:
    source: str
    status: str           # ok | stale | unavailable
    as_of: datetime | None = None
    reason: str | None = None


@dataclass
class CustomerView:
    account: Account
    usage: list[UsageMonth] | None
    active_cases: list[Case] | None
    sources: list[SourceStatus] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return any(s.status != "ok" for s in self.sources)


def upstream_to_problem(exc: UpstreamError) -> errors.ProblemError:
    if exc.kind is UpstreamErrorKind.TIMEOUT:
        return errors.upstream_timeout(exc.source)
    if exc.kind is UpstreamErrorKind.BAD_RESPONSE:
        return errors.upstream_bad_response(exc.source)
    return errors.upstream_unavailable(exc.source, exc.kind.value)


class CustomerService:
    def __init__(self, entitlements: EntitlementPort, usage: UsagePort, cases: CaseSystemPort,
                 clock: Clock) -> None:
        self._ent = entitlements
        self._usage = usage
        self._cases = cases
        self._clock = clock

    async def get_view(self, account_id: str) -> CustomerView:
        ent_res, usage_res, cases_res = await asyncio.gather(
            self._ent.get_account(account_id),
            self._usage.monthly_usage(account_id, months=3),
            self._cases.list_cases(account_id=account_id, statuses=sorted(ACTIVE_STATUSES)),
            return_exceptions=True,
        )
        if isinstance(ent_res, UpstreamError):
            if ent_res.kind is UpstreamErrorKind.NOT_FOUND:
                raise errors.not_found("Customer", account_id)
            raise upstream_to_problem(ent_res)
        if isinstance(ent_res, BaseException):
            raise ent_res
        now = self._clock()
        sources = [SourceStatus("entitlements", "stale" if ent_res.stale else "ok", ent_res.as_of,
                                "served from CSV/XML snapshot" if ent_res.stale else None)]

        usage: list[UsageMonth] | None = None
        if isinstance(usage_res, UpstreamError):
            sources.append(SourceStatus("usage", "unavailable", None, usage_res.kind.value))
        elif isinstance(usage_res, BaseException):
            raise usage_res
        else:
            usage = usage_res
            sources.append(SourceStatus("usage", "ok", now))

        active: list[Case] | None = None
        if isinstance(cases_res, UpstreamError):
            sources.append(SourceStatus("cases", "unavailable", None, cases_res.kind.value))
        elif isinstance(cases_res, BaseException):
            raise cases_res
        else:
            active = cases_res
            sources.append(SourceStatus("cases", "ok", now))

        return CustomerView(account=ent_res.account, usage=usage, active_cases=active, sources=sources)


def case_counts(cases: list[Case]) -> dict[str, int]:
    return {
        "active": len(cases),
        "activeP1": sum(1 for c in cases if c.priority is Priority.P1),
        "escalated": sum(1 for c in cases if c.escalation.level > 0),
    }
