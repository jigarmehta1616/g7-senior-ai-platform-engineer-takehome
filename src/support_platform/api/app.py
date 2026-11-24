"""Application factory.

Contract-first: ``openapi.yaml`` (repo root) is the source of truth and is served as-is.
FastAPI's generated schema is disabled so there is exactly one contract; the contract
tests (tests/contract) fail if routes and spec drift apart."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from support_platform.api.middleware import install_middleware
from support_platform.api.problems import install_exception_handlers
from support_platform.api.routes import admin, cases, customers, ops
from support_platform.config import Settings, utc_now
from support_platform.container import build_container
from support_platform.domain.types import Clock
from support_platform.events.outbox import run_event_loop
from support_platform.observability.logging import configure_logging

log = logging.getLogger("support_platform")
REPO_ROOT = Path(__file__).resolve().parents[3]


def _locate(env_var: str, default: Path) -> Path:
    return Path(os.getenv(env_var, str(default)))


def create_app(settings: Settings | None = None, *, clock: Clock = utc_now,
               upstream_transport: httpx.AsyncBaseTransport | None = None,
               webhook_transport: httpx.AsyncBaseTransport | None = None,
               run_background: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    container = build_container(settings, clock=clock, upstream_transport=upstream_transport,
                                webhook_transport=webhook_transport)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await container.entitlements.refresh_snapshot()
        container.idempotency.purge_expired()          # TTL sweep of idempotency records
        tasks: list[asyncio.Task] = []
        if run_background:
            tasks.append(asyncio.create_task(run_event_loop(container.outbox, container.relay, container.dispatcher,
                                                            settings.webhook_poll_interval_s)))
        log.info("api started", extra={"env": settings.env})
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await container.aclose()

    app = FastAPI(
        title="Customer Entitlement & Support Case API",
        version="1.0.0",
        openapi_url=None, docs_url=None, redoc_url=None,
        lifespan=lifespan,
    )
    app.state.container = container
    install_exception_handlers(app)
    install_middleware(app)

    public_routers = [ops.build_router(_locate("SPEC_PATH", REPO_ROOT / "openapi.yaml")), customers.router,
                      cases.router, admin.router]
    for router in public_routers:
        app.include_router(router)
    app.state.public_routers = public_routers      # contract tests diff these against openapi.yaml
    if settings.enable_dev_idp:
        app.include_router(ops.dev_router)
    console_dir = _locate("CONSOLE_DIR", REPO_ROOT / "frontend" / "dist")   # Vite build output
    if settings.enable_console and console_dir.is_dir():
        app.mount("/console", StaticFiles(directory=console_dir, html=True), name="console")
    return app
