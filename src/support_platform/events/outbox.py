"""Event-driven path for ``case.escalated`` (the chosen stretch goal).

    escalate() --enqueue--> outbox_events (SQLite, same process)
                                 |
                    OutboxRelay.publish_pending()       <- at-least-once relay
                     |                         |
           in-process EventBus          webhook_deliveries (one row per subscription)
           (stand-in for Kafka /                 |
            EventBridge topic)          WebhookDispatcher.deliver_due()
                                          signed POST, exponential backoff, dead-letter

Swapping the EventBus for Kafka/EventBridge only changes ``EventBus.publish``; the outbox
guarantees we never publish an event for a write that didn't happen (or lose one that did).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx

from support_platform.domain.types import Clock
from support_platform.observability.logging import correlation_id_var
from support_platform.persistence.db import Database
from support_platform.security.webhook_signing import signed_headers

log = logging.getLogger("support_platform.events")
Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Minimal in-process pub/sub. Topic == event type."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = {}

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subs.setdefault(event_type, []).append(handler)

    async def publish(self, event: dict[str, Any]) -> None:
        for handler in self._subs.get(event["type"], []):
            try:
                await handler(event)
            except Exception:  # a bad consumer must not block the relay
                log.exception("event handler failed", extra={"event_type": event["type"]})


class OutboxPublisher:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock
        self.wakeup = asyncio.Event()

    def enqueue(self, event_type: str, *, source: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {
            "specversion": "1.0",                 # CloudEvents 1.0 envelope
            "id": "evt_" + uuid.uuid4().hex,
            "type": event_type,
            "source": source,
            "time": self._clock().isoformat(),
            "datacontenttype": "application/json",
            "correlationid": correlation_id_var.get(),
            "data": data,
        }
        with self._db.tx() as conn:
            conn.execute("INSERT INTO outbox_events (id, event_type, payload, occurred_at) VALUES (?, ?, ?, ?)",
                         (event["id"], event_type, json.dumps(event), event["time"]))
        self.wakeup.set()
        return event


class OutboxRelay:
    def __init__(self, db: Database, bus: EventBus, clock: Clock) -> None:
        self._db = db
        self._bus = bus
        self._clock = clock

    async def publish_pending(self, batch: int = 100) -> int:
        rows = self._db.query("SELECT id, event_type, payload FROM outbox_events WHERE published_at IS NULL"
                              " ORDER BY occurred_at LIMIT ?", (batch,))
        for row in rows:
            event = json.loads(row["payload"])
            subs = self._db.query("SELECT id, event_types FROM webhook_subscriptions WHERE status = 'active'")
            now = self._clock().isoformat()
            with self._db.tx() as conn:
                for sub in subs:
                    if row["event_type"] in json.loads(sub["event_types"]):
                        conn.execute(
                            "INSERT OR IGNORE INTO webhook_deliveries (id, event_id, subscription_id, status,"
                            " attempts, next_attempt_at, updated_at) VALUES (?, ?, ?, 'pending', 0, ?, ?)",
                            ("dlv_" + uuid.uuid4().hex, row["id"], sub["id"], now, now))
                conn.execute("UPDATE outbox_events SET published_at = ? WHERE id = ?", (now, row["id"]))
            await self._bus.publish(event)
        return len(rows)


class WebhookDispatcher:
    def __init__(self, db: Database, client: httpx.AsyncClient, clock: Clock, *, max_attempts: int,
                 timeout_s: float = 5.0) -> None:
        self._db = db
        self._client = client
        self._clock = clock
        self._max_attempts = max_attempts
        self._timeout_s = timeout_s

    def _backoff(self, attempts: int) -> timedelta:
        return timedelta(seconds=min(2 ** attempts, 3600))

    async def deliver_due(self, batch: int = 50) -> int:
        now = self._clock()
        rows = self._db.query(
            "SELECT d.id, d.attempts, d.event_id, s.url, s.secret, e.payload FROM webhook_deliveries d"
            " JOIN webhook_subscriptions s ON s.id = d.subscription_id"
            " JOIN outbox_events e ON e.id = d.event_id"
            " WHERE d.status = 'pending' AND d.next_attempt_at <= ? AND s.status = 'active'"
            " ORDER BY d.next_attempt_at LIMIT ?", (now.isoformat(), batch))
        for r in rows:
            body = r["payload"].encode()
            headers = {"content-type": "application/json", "user-agent": "support-platform-webhooks/1.0",
                       **signed_headers(r["secret"], r["event_id"], body)}
            status_code: int | None = None
            error: str | None = None
            try:
                resp = await asyncio.wait_for(self._client.post(r["url"], content=body, headers=headers),
                                              timeout=self._timeout_s)
                status_code = resp.status_code
                ok = 200 <= resp.status_code < 300
            except (httpx.HTTPError, TimeoutError) as exc:
                ok, error = False, type(exc).__name__
            attempts = r["attempts"] + 1
            if ok:
                new_status, next_at = "delivered", now
            elif attempts >= self._max_attempts:
                new_status, next_at = "dead", now
                log.error("webhook dead-lettered", extra={"delivery_id": r["id"], "url": r["url"]})
            else:
                new_status, next_at = "pending", now + self._backoff(attempts)
            with self._db.tx() as conn:
                conn.execute("UPDATE webhook_deliveries SET status = ?, attempts = ?, next_attempt_at = ?,"
                             " last_status_code = ?, last_error = ?, updated_at = ? WHERE id = ?",
                             (new_status, attempts, next_at.isoformat(), status_code, error, now.isoformat(),
                              r["id"]))
            log.info("webhook delivery attempt", extra={"delivery_id": r["id"], "status": new_status,
                                                        "http_status": status_code, "attempt": attempts})
        return len(rows)


async def run_event_loop(publisher: OutboxPublisher, relay: OutboxRelay, dispatcher: WebhookDispatcher,
                         poll_interval_s: float) -> None:
    """Background task: wake on enqueue (low latency) or poll (retries / crash recovery)."""
    while True:
        try:
            await relay.publish_pending()
            await dispatcher.deliver_due()
        except Exception:
            log.exception("event loop iteration failed")
        try:
            await asyncio.wait_for(publisher.wakeup.wait(), timeout=poll_interval_s)
        except TimeoutError:
            pass
        publisher.wakeup.clear()
