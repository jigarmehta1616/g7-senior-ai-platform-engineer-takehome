"""Adapter for the entitlement system (NetSuite-like).

Primary path: REST lookup. Fallback: an in-memory snapshot built from the CSV export +
XML change feed (refreshed on start-up and periodically). When the REST path fails we
serve the snapshot and flag the data as ``stale`` rather than failing the request."""

from __future__ import annotations

import logging
from datetime import datetime

from support_platform.domain.models import Account
from support_platform.domain.types import AccountResult, Clock
from support_platform.upstreams.http import UpstreamHttp
from support_platform.upstreams.resilience import UpstreamError, UpstreamErrorKind
from support_platform.upstreams.translators import (
    TranslationError,
    account_from_upstream,
    accounts_from_csv,
    apply_xml_feed,
)

log = logging.getLogger("support_platform.entitlements")


class EntitlementClient:
    def __init__(self, http: UpstreamHttp, clock: Clock) -> None:
        self.http = http
        self._clock = clock
        self._snapshot: dict[str, Account] = {}
        self._snapshot_at: datetime | None = None

    async def refresh_snapshot(self) -> bool:
        try:
            csv_text = await self.http.get_text("/entitlements/export.csv")
            xml_text = await self.http.get_text("/entitlements/feed.xml")
            self._snapshot = apply_xml_feed(accounts_from_csv(csv_text), xml_text)
            self._snapshot_at = self._clock()
            log.info("entitlement snapshot refreshed", extra={"accounts": len(self._snapshot)})
            return True
        except (UpstreamError, TranslationError, ValueError) as exc:
            log.warning("entitlement snapshot refresh failed", extra={"error": str(exc)})
            return False

    async def get_account(self, account_id: str) -> AccountResult:
        try:
            raw = await self.http.get_json(f"/entitlements/api/accounts/{account_id}")
            return AccountResult(account_from_upstream(raw), stale=False, as_of=self._clock())
        except TranslationError as exc:
            raise UpstreamError("entitlements", UpstreamErrorKind.BAD_RESPONSE, str(exc)) from exc
        except UpstreamError as exc:
            if exc.kind is UpstreamErrorKind.NOT_FOUND:
                raise
            cached = self._snapshot.get(account_id)
            if cached is not None and self._snapshot_at is not None:
                log.warning("serving entitlement from snapshot", extra={"account_id": account_id,
                                                                        "reason": exc.kind})
                return AccountResult(cached, stale=True, as_of=self._snapshot_at)
            raise

    async def list_accounts(self) -> tuple[list[Account], bool]:
        """Used for cross-system case filters (tier / renewal). Returns (accounts, stale)."""
        try:
            body = await self.http.get_json("/entitlements/api/accounts")
            return [account_from_upstream(r) for r in body["items"]], False
        except (UpstreamError, TranslationError, KeyError):
            if self._snapshot:
                return list(self._snapshot.values()), True
            raise
