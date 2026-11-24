"""Adapter for the case system (Salesforce-like REST)."""

from __future__ import annotations

from support_platform.domain.models import Case, CaseStatus, Comment, CommentVisibility, Priority
from support_platform.upstreams.http import UpstreamHttp, _json
from support_platform.upstreams.resilience import UpstreamError, UpstreamErrorKind
from support_platform.upstreams.translators import (
    TranslationError,
    case_from_upstream,
    status_to_upstream,
)


class CaseSystemClient:
    def __init__(self, http: UpstreamHttp) -> None:
        self.http = http

    async def list_cases(self, *, account_id: str | None = None, statuses: list[CaseStatus] | None = None,
                         priorities: list[Priority] | None = None) -> list[Case]:
        """Push down what the upstream can filter on; the service filters the rest."""
        params: dict[str, str] = {}
        if account_id:
            params["accountId"] = account_id
        if statuses:
            params["status"] = ",".join(status_to_upstream(s) for s in statuses)
        if priorities:
            params["priority"] = ",".join(p.value for p in priorities)
        body = await self.http.get_json("/cases/api/cases", params=params)
        try:
            return [case_from_upstream(r) for r in body["records"]]
        except (KeyError, TranslationError) as exc:
            raise UpstreamError("cases", UpstreamErrorKind.BAD_RESPONSE, str(exc)) from exc

    async def get_case(self, case_id: str) -> Case:
        body = await self.http.get_json(f"/cases/api/cases/{case_id}")
        try:
            return case_from_upstream(body)
        except TranslationError as exc:
            raise UpstreamError("cases", UpstreamErrorKind.BAD_RESPONSE, str(exc)) from exc

    async def add_comment(self, case_id: str, *, author: str, body: str, visibility: CommentVisibility,
                          idempotency_key: str) -> Comment:
        # Safe to retry: the upstream de-duplicates on the forwarded Idempotency-Key.
        resp = await self.http.request(
            "POST", f"/cases/api/cases/{case_id}/comments", retry=True,
            json={"author": author, "body": body, "visibility": visibility.value},
            headers={"Idempotency-Key": idempotency_key},
        )
        raw = _json("cases", resp)
        case_stub = {"id": case_id, "accountId": "-", "priority": "P3", "Status": "open",
                     "openedAt": raw["at"], "Comments": [raw]}
        comment = case_from_upstream(case_stub).comments
        assert comment
        return comment[0]

    async def apply_escalation(self, case_id: str, *, expected_version: int, level: int, target_team: str,
                               reason: str) -> Case:
        # Not retried: a lost response + retry would hit 412 on the version check, which is
        # the correct, safe outcome (the caller re-reads and sees the escalation applied).
        resp = await self.http.request(
            "PATCH", f"/cases/api/cases/{case_id}", retry=False,
            json={"escalationLevel": level, "escalatedTo": target_team, "escalationReason": reason},
            headers={"If-Match": str(expected_version)},
        )
        return case_from_upstream(_json("cases", resp))
