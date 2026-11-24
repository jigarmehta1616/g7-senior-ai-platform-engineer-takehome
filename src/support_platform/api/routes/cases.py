from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from support_platform.api.deps import get_container, require_scopes
from support_platform.api.presenters import case_detail, case_summary, comment
from support_platform.container import Container
from support_platform.domain import errors
from support_platform.domain.models import CaseStatus, CommentCreate, EscalateRequest, Priority, SupportTier
from support_platform.security.auth import CASES_ESCALATE, CASES_READ, CASES_WRITE, Principal
from support_platform.services.cases import CaseQuery, CaseSort
from support_platform.services.idempotency import request_fingerprint

router = APIRouter(prefix="/v1/cases", tags=["cases"])

CaseId = Annotated[str, Path(pattern=r"^CS-[0-9]{3,12}$")]
E = TypeVar("E", bound=Enum)

# Deprecated alias kept for one version; see "Versioning & deprecation" in openapi.yaml.
_DEPRECATION_HEADERS = {
    "Deprecation": "@1767225600",                         # RFC 9745: deprecated since 2026-01-01
    "Sunset": "Wed, 30 Jun 2027 00:00:00 GMT",            # RFC 8594
    "Link": '<https://api.example.com/docs/deprecations#account_id>; rel="deprecation"',
}


def _csv_enum(raw: str | None, enum: type[E], name: str) -> tuple[E, ...]:
    if not raw:
        return ()
    out = []
    for part in (p for p in raw.split(",") if p.strip()):
        try:
            out.append(enum(part.strip()))
        except ValueError as exc:
            allowed = ", ".join(e.value for e in enum)
            raise errors.validation_error(
                f"Invalid {name} '{part}'. Allowed: {allowed}",
                [{"pointer": f"query/{name}", "detail": f"must be one of: {allowed}"}],
            ) from exc
    return tuple(dict.fromkeys(out))


@router.get("")
async def list_cases(
    response: Response,
    status: Annotated[str | None, Query(max_length=200)] = None,
    priority: Annotated[str | None, Query(max_length=20)] = None,
    accountId: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")] = None,
    account_id: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$", deprecated=True)] = None,
    supportTier: SupportTier | None = None,
    renewalBefore: date | None = None,
    openedBefore: datetime | None = None,
    openedAfter: datetime | None = None,
    sort: CaseSort = CaseSort.OPENED_DESC,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    include: Annotated[str | None, Query(pattern=r"^account$")] = None,
    _: Principal = Depends(require_scopes(CASES_READ)),
    c: Container = Depends(get_container),
) -> dict:
    for name, value in (("openedBefore", openedBefore), ("openedAfter", openedAfter)):
        if value is not None and value.tzinfo is None:
            raise errors.validation_error(f"{name} must include a timezone offset (e.g. Z).",
                                          [{"pointer": f"query/{name}", "detail": "timezone required"}])
    if account_id and not accountId:
        accountId = account_id
        response.headers.update(_DEPRECATION_HEADERS)
    q = CaseQuery(
        statuses=_csv_enum(status, CaseStatus, "status"),
        priorities=_csv_enum(priority, Priority, "priority"),
        account_id=accountId, support_tier=supportTier, renewal_before=renewalBefore,
        opened_before=openedBefore, opened_after=openedAfter, sort=sort, limit=limit, cursor=cursor,
        include_account=include == "account",
    )
    page = await c.cases.search(q)
    now = c.clock()
    return {
        "data": [case_summary(x, now, page.accounts.get(x.account_id), q.include_account) for x in page.items],
        "page": {"limit": limit, "nextCursor": page.next_cursor},
        "degraded": bool(page.stale_sources),
        "staleSources": page.stale_sources,
    }


@router.get("/{caseId}")
async def get_case(
    caseId: CaseId,
    if_none_match: Annotated[str | None, Header()] = None,
    _: Principal = Depends(require_scopes(CASES_READ)),
    c: Container = Depends(get_container),
) -> Response:
    case = await c.cases.get(caseId)
    if if_none_match and case.etag in [t.strip().removeprefix("W/") for t in if_none_match.split(",")]:
        return Response(status_code=304, headers={"ETag": case.etag})
    return JSONResponse(case_detail(case, c.clock()), headers={"ETag": case.etag})


@router.post("/{caseId}/comments", status_code=201)
async def add_comment(
    request: Request,
    caseId: CaseId,
    body: CommentCreate,
    idempotency_key: Annotated[str | None, Header()] = None,
    principal: Principal = Depends(require_scopes(CASES_WRITE)),
    c: Container = Depends(get_container),
) -> Response:
    key = c.idempotency.validate_key(idempotency_key)
    scope = principal.rate_limit_key
    fingerprint = request_fingerprint("POST", request.url.path, body.model_dump(mode="json"))
    stored = c.idempotency.begin(scope, key, "POST", request.url.path, fingerprint)
    if stored is not None:
        request.state.audit_details = {"idempotentReplay": True}
        return JSONResponse(stored.body, status_code=stored.status,
                            headers={**stored.headers, "Idempotency-Replayed": "true"})
    try:
        created = await c.cases.add_comment(caseId, body, principal, key)
    except BaseException:
        c.idempotency.abandon(scope, key)
        raise
    payload = comment(created)
    headers = {"Location": f"/v1/cases/{caseId}/comments/{created.id}"}
    c.idempotency.complete(scope, key, 201, payload, headers)
    request.state.audit_details = {"commentId": created.id, "visibility": created.visibility.value}
    return JSONResponse(payload, status_code=201, headers=headers)


@router.post("/{caseId}/escalate")
async def escalate_case(
    request: Request,
    caseId: CaseId,
    body: EscalateRequest,
    if_match: Annotated[str | None, Header()] = None,
    principal: Principal = Depends(require_scopes(CASES_ESCALATE)),
    c: Container = Depends(get_container),
) -> Response:
    request.state.audit_details = {"reason": body.reason.value, "note": body.note}
    updated = await c.cases.escalate(caseId, body, principal, if_match)
    return JSONResponse(case_detail(updated, c.clock()), headers={"ETag": updated.etag})
