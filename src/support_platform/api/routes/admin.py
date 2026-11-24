"""Webhook subscriptions + audit log read API (governance surface)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from support_platform.api.deps import get_container, require_scopes
from support_platform.container import Container
from support_platform.domain.models import WebhookSubscriptionCreate
from support_platform.security.auth import AUDIT_READ, WEBHOOKS_MANAGE, Principal

router = APIRouter(tags=["governance"])
SubId = Annotated[str, Path(pattern=r"^whs_[A-Za-z0-9_]{4,40}$")]


@router.post("/v1/webhook-subscriptions", status_code=201)
async def create_subscription(
    request: Request, body: WebhookSubscriptionCreate, response: Response,
    principal: Principal = Depends(require_scopes(WEBHOOKS_MANAGE)), c: Container = Depends(get_container),
) -> dict:
    sub = c.webhooks.create(body, principal.subject)
    response.headers["Location"] = f"/v1/webhook-subscriptions/{sub['id']}"
    request.state.audit_details = {"url": sub["url"], "eventTypes": sub["eventTypes"]}
    return sub


@router.get("/v1/webhook-subscriptions")
async def list_subscriptions(_: Principal = Depends(require_scopes(WEBHOOKS_MANAGE)),
                             c: Container = Depends(get_container)) -> dict:
    return {"data": c.webhooks.list_all()}


@router.delete("/v1/webhook-subscriptions/{subscriptionId}", status_code=204)
async def disable_subscription(subscriptionId: SubId,
                               _: Principal = Depends(require_scopes(WEBHOOKS_MANAGE)),
                               c: Container = Depends(get_container)) -> Response:
    c.webhooks.disable(subscriptionId)
    return Response(status_code=204)


@router.get("/v1/webhook-subscriptions/{subscriptionId}/deliveries")
async def list_deliveries(subscriptionId: SubId,
                          _: Principal = Depends(require_scopes(WEBHOOKS_MANAGE)),
                          c: Container = Depends(get_container)) -> dict:
    return {"data": c.webhooks.deliveries(subscriptionId)}


@router.get("/v1/audit-events")
async def list_audit_events(
    actor: Annotated[str | None, Query(max_length=200)] = None,
    agent: Annotated[str | None, Query(max_length=100)] = None,
    resourceId: Annotated[str | None, Query(max_length=64)] = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _: Principal = Depends(require_scopes(AUDIT_READ)),
    c: Container = Depends(get_container),
) -> dict:
    rows = c.audit.list(actor=actor, agent=agent, resource_id=resourceId, after_seq=before, limit=limit)
    chain_ok, checked = c.audit.verify_chain()
    data = [{
        "seq": r["seq"], "eventId": r["event_id"], "occurredAt": r["occurred_at"], "correlationId": r["correlation_id"],
        "actor": {"subject": r["actor_subject"], "agent": r["actor_agent"], "clientId": r["client_id"]},
        "action": r["action"], "resourceType": r["resource_type"], "resourceId": r["resource_id"],
        "outcome": r["outcome"], "httpStatus": r["http_status"], "hash": r["hash"],
    } for r in rows]
    return {"data": data, "page": {"nextBefore": data[-1]["seq"] if len(data) == limit else None},
            "integrity": {"chainValid": chain_ok, "eventsChecked": checked}}
