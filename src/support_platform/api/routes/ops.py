"""Health probes, contract serving, and the local-only dev token endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from support_platform.api.deps import get_container
from support_platform.container import Container
from support_platform.domain import errors
from support_platform.security.dev_idp import PERSONA_GRANT, PERSONAS, TOKEN_EXCHANGE


def build_router(spec_path: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", tags=["operations"])
    async def healthz() -> dict:
        return {"status": "ok"}

    @router.get("/readyz", tags=["operations"])
    async def readyz(c: Container = Depends(get_container)) -> JSONResponse:
        db_ok = c.db.ping()
        upstreams = {name: b.state.value for name, b in c.breakers.items()}
        return JSONResponse({"status": "ready" if db_ok else "not_ready", "database": "ok" if db_ok else "down",
                             "upstreams": upstreams}, status_code=200 if db_ok else 503)

    @router.get("/openapi.yaml", include_in_schema=False)
    async def spec() -> FileResponse:
        return FileResponse(spec_path, media_type="application/yaml")

    @router.get("/docs", include_in_schema=False)
    async def docs() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.yaml", title="Support Platform API")

    return router


dev_router = APIRouter(prefix="/dev", include_in_schema=False)


@dev_router.get("/personas")
async def personas() -> dict:
    return {"personas": [{"id": k, "subject": p.subject, "name": p.display_name, "scopes": sorted(p.scopes)}
                         for k, p in PERSONAS.items()]}


@dev_router.post("/oauth/token")
async def token(request: Request, c: Container = Depends(get_container)) -> JSONResponse:
    """OAuth 2.0 token endpoint (form-encoded per RFC 6749; JSON accepted for convenience)."""
    assert c.dev_idp is not None
    raw = await request.body()
    if request.headers.get("content-type", "").startswith("application/json"):
        form = {k: str(v) for k, v in json.loads(raw or b"{}").items()}
    else:
        form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
    grant = form.get("grant_type")
    if grant == PERSONA_GRANT:
        result = c.dev_idp.issue_persona_token(form.get("persona", ""))
    elif grant == TOKEN_EXCHANGE:
        result = c.dev_idp.exchange(form.get("subject_token", ""), form.get("actor_client", ""), form.get("scope"))
    else:
        raise errors.validation_error(f"unsupported grant_type; use {PERSONA_GRANT} or {TOKEN_EXCHANGE}")
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
