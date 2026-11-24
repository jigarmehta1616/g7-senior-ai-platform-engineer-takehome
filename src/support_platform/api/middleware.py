"""Cross-cutting HTTP concerns, in one middleware so ordering is obvious:

1. correlation ID (accept well-formed inbound ``X-Correlation-ID`` or mint one)
2. request body size guard
3. call the app
4. rate-limit + security headers on the way out
5. audit: every mutation, every agent (delegated) call, every authorization denial
6. one structured access-log line"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from support_platform.api.problems import problem_response
from support_platform.domain import errors
from support_platform.observability.logging import accept_or_create_correlation_id, correlation_id_var
from support_platform.services.audit import AuditEntry

log = logging.getLogger("support_platform.access")

_RESOURCE_TYPES = {"cases": "case", "customers": "customer", "webhook-subscriptions": "webhook_subscription",
                   "audit-events": "audit_event"}


def _resource(request: Request) -> tuple[str | None, str | None]:
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    parts = [p for p in template.split("/") if p]
    rtype = _RESOURCE_TYPES.get(parts[1]) if len(parts) > 1 else None
    params = request.scope.get("path_params") or {}
    rid = next(iter(params.values()), None) if params else None
    return rtype, rid


class PlatformMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = accept_or_create_correlation_id(request.headers.get("x-correlation-id"))
        token = correlation_id_var.set(cid)
        started = time.perf_counter()
        container = request.app.state.container
        try:
            length = request.headers.get("content-length")
            limit = container.settings.max_body_bytes
            if length and length.isdigit() and int(length) > limit:
                response: Response = problem_response(request, errors.payload_too_large(limit))
            else:
                response = await call_next(request)

            response.headers["X-Correlation-ID"] = cid
            rate = getattr(request.state, "rate", None)
            if rate is not None:
                response.headers["RateLimit-Limit"] = str(rate.limit)
                response.headers["RateLimit-Remaining"] = str(rate.remaining)
                response.headers["RateLimit-Reset"] = str(rate.reset_s)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            if request.url.path.startswith("/v1/"):
                response.headers.setdefault("Cache-Control", "no-store")

            principal = getattr(request.state, "principal", None)
            if principal is not None and (
                request.method not in ("GET", "HEAD", "OPTIONS") or principal.is_agent or response.status_code == 403
            ):
                rtype, rid = _resource(request)
                route = request.scope.get("route")
                status = response.status_code
                container.audit.record(AuditEntry(
                    correlation_id=cid,
                    actor_subject=principal.subject,
                    actor_agent=principal.actor,
                    client_id=principal.client_id,
                    action=f"{request.method} {getattr(route, 'path', request.url.path)}",
                    resource_type=rtype,
                    resource_id=rid,
                    outcome="success" if status < 400 else ("denied" if status in (401, 403, 429) else "failed"),
                    http_status=status,
                    details={"query": dict(request.query_params), "tool": request.headers.get("x-agent-tool"),
                             **getattr(request.state, "audit_details", {})},
                ))
            log.info("request", extra={
                "method": request.method, "path": request.url.path, "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "subject": getattr(principal, "subject", None), "agent": getattr(principal, "actor", None),
            })
            return response
        finally:
            correlation_id_var.reset(token)


def install_middleware(app: FastAPI) -> None:
    app.add_middleware(PlatformMiddleware)
