"""Composition root: builds every collaborator once, explicitly. Tests swap the transport
(in-process mock upstreams) and the clock; nothing else needs patching."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from support_platform.config import Settings, utc_now
from support_platform.domain.cursor import CursorCodec
from support_platform.domain.models import WebhookSubscriptionCreate
from support_platform.domain.types import Clock
from support_platform.events.outbox import EventBus, OutboxPublisher, OutboxRelay, WebhookDispatcher
from support_platform.persistence.db import Database
from support_platform.security.auth import TokenVerifier
from support_platform.security.dev_idp import DevIdentityProvider
from support_platform.services.audit import AuditService
from support_platform.services.cases import CaseService
from support_platform.services.customers import CustomerService
from support_platform.services.idempotency import IdempotencyService
from support_platform.services.rate_limit import RateLimiter
from support_platform.services.webhooks import WebhookService
from support_platform.upstreams.case_system import CaseSystemClient
from support_platform.upstreams.entitlements import EntitlementClient
from support_platform.upstreams.http import UpstreamHttp
from support_platform.upstreams.resilience import CircuitBreaker, RetryPolicy
from support_platform.upstreams.usage import UsageClient

DEMO_SUBSCRIPTION_ID = "whs_demo_receiver"


@dataclass
class Container:
    settings: Settings
    clock: Clock
    db: Database
    http_client: httpx.AsyncClient
    webhook_client: httpx.AsyncClient
    verifier: TokenVerifier
    dev_idp: DevIdentityProvider | None
    rate_limiter: RateLimiter
    idempotency: IdempotencyService
    audit: AuditService
    entitlements: EntitlementClient
    case_client: CaseSystemClient
    usage_client: UsageClient
    customers: CustomerService
    cases: CaseService
    webhooks: WebhookService
    bus: EventBus
    outbox: OutboxPublisher
    relay: OutboxRelay
    dispatcher: WebhookDispatcher
    breakers: dict[str, CircuitBreaker]

    async def aclose(self) -> None:
        await self.http_client.aclose()
        if self.webhook_client is not self.http_client:
            await self.webhook_client.aclose()
        self.db.close()


def build_container(settings: Settings, *, clock: Clock = utc_now,
                    upstream_transport: httpx.AsyncBaseTransport | None = None,
                    webhook_transport: httpx.AsyncBaseTransport | None = None,
                    monotonic: object = time.monotonic) -> Container:
    db = Database(settings.db_path)
    db.migrate()

    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    http_client = httpx.AsyncClient(transport=upstream_transport, limits=limits)
    webhook_client = (httpx.AsyncClient(transport=webhook_transport, follow_redirects=False)
                      if webhook_transport or upstream_transport is None
                      else httpx.AsyncClient(transport=upstream_transport, follow_redirects=False))
    policy = RetryPolicy(settings.retry_attempts, settings.retry_base_delay_s, settings.retry_max_delay_s)
    breakers: dict[str, CircuitBreaker] = {}

    def upstream(name: str) -> UpstreamHttp:
        breakers[name] = CircuitBreaker(name, settings.breaker_failure_threshold, settings.breaker_reset_timeout_s,
                                        clock=monotonic)  # type: ignore[arg-type]
        return UpstreamHttp(name, http_client, settings.upstream_base_url, timeout_s=settings.upstream_timeout_s,
                            deadline_s=settings.upstream_deadline_s, breaker=breakers[name], policy=policy)

    case_client = CaseSystemClient(upstream("cases"))
    entitlements = EntitlementClient(upstream("entitlements"), clock)
    usage_client = UsageClient(upstream("usage"))

    verifier = TokenVerifier(settings.jwt_secret, settings.jwt_issuer, settings.jwt_audience)
    dev_idp = (DevIdentityProvider(settings.jwt_secret, settings.jwt_issuer, settings.jwt_audience, verifier)
               if settings.enable_dev_idp else None)

    bus = EventBus()
    outbox = OutboxPublisher(db, clock)
    webhooks = WebhookService(db, clock, allow_http=settings.is_local)
    if settings.seed_demo_webhook:
        webhooks.create(WebhookSubscriptionCreate(url=settings.upstream_base_url + "/_receiver/webhooks",
                                                  eventTypes=["case.escalated"],
                                                  description="Local demo receiver (mock upstreams)"),
                        created_by="system", secret=settings.demo_receiver_secret, sub_id=DEMO_SUBSCRIPTION_ID)

    return Container(
        settings=settings, clock=clock, db=db, http_client=http_client, webhook_client=webhook_client,
        verifier=verifier, dev_idp=dev_idp, rate_limiter=RateLimiter(),
        idempotency=IdempotencyService(db, clock, settings.idempotency_ttl_hours),
        audit=AuditService(db, clock), entitlements=entitlements, case_client=case_client,
        usage_client=usage_client,
        customers=CustomerService(entitlements, usage_client, case_client, clock),
        cases=CaseService(case_client, entitlements, outbox, CursorCodec(settings.cursor_secret), clock),
        webhooks=webhooks, bus=bus, outbox=outbox, relay=OutboxRelay(db, bus, clock),
        dispatcher=WebhookDispatcher(db, webhook_client, clock, max_attempts=settings.webhook_max_attempts),
        breakers=breakers,
    )
