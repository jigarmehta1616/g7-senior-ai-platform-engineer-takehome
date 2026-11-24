"""FastAPI dependencies: container access, authentication, scope checks, rate limiting."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from support_platform.container import Container
from support_platform.domain import errors
from support_platform.security.auth import Principal, parse_bearer


def get_container(request: Request) -> Container:
    return request.app.state.container


def authenticated(request: Request, c: Container = Depends(get_container)) -> Principal:
    principal = c.verifier.verify(parse_bearer(request.headers.get("authorization")))
    request.state.principal = principal
    budget = c.settings.rate_limit_agent_per_min if principal.is_agent else c.settings.rate_limit_user_per_min
    decision = c.rate_limiter.check(principal.rate_limit_key, budget)
    request.state.rate = decision
    if not decision.allowed:
        raise errors.rate_limited(decision.reset_s, decision.limit)
    return principal


def require_scopes(*scopes: str) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(authenticated)) -> Principal:
        principal.require(*scopes)
        return principal

    return dependency
