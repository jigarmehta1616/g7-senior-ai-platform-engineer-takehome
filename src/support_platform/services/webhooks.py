"""Webhook subscription management."""

from __future__ import annotations

import json
import uuid
from typing import Any

from support_platform.domain import errors
from support_platform.domain.models import WebhookSubscriptionCreate
from support_platform.domain.types import Clock
from support_platform.persistence.db import Database
from support_platform.security.webhook_signing import generate_secret

SUPPORTED_EVENTS = frozenset({"case.escalated"})


class WebhookService:
    def __init__(self, db: Database, clock: Clock, *, allow_http: bool) -> None:
        self._db = db
        self._clock = clock
        self._allow_http = allow_http

    def create(self, req: WebhookSubscriptionCreate, created_by: str, *, secret: str | None = None,
               sub_id: str | None = None) -> dict[str, Any]:
        unknown = set(req.event_types) - SUPPORTED_EVENTS
        if unknown:
            raise errors.validation_error(f"Unsupported event types: {', '.join(sorted(unknown))}",
                                          [{"pointer": "/eventTypes", "detail": "unsupported event type"}])
        if req.url.startswith("http://") and not self._allow_http:
            raise errors.validation_error("Webhook URLs must use https.", [{"pointer": "/url", "detail": "https only"}])
        sid = sub_id or "whs_" + uuid.uuid4().hex[:20]
        secret = secret or generate_secret()
        created_at = self._clock().isoformat()
        with self._db.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO webhook_subscriptions (id, url, event_types, secret, description,"
                         " status, created_by, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                         (sid, req.url, json.dumps(sorted(set(req.event_types))), secret, req.description,
                          created_by, created_at))
        out = self.get(sid)
        out["secret"] = secret   # returned once, at creation only
        return out

    def get(self, sub_id: str) -> dict[str, Any]:
        rows = self._db.query("SELECT * FROM webhook_subscriptions WHERE id = ?", (sub_id,))
        if not rows:
            raise errors.not_found("Webhook subscription", sub_id)
        return self._present(rows[0])

    def list_all(self) -> list[dict[str, Any]]:
        return [self._present(r) for r in self._db.query("SELECT * FROM webhook_subscriptions ORDER BY created_at")]

    def disable(self, sub_id: str) -> None:
        self.get(sub_id)
        with self._db.tx() as conn:
            conn.execute("UPDATE webhook_subscriptions SET status = 'disabled' WHERE id = ?", (sub_id,))

    def deliveries(self, sub_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.get(sub_id)
        rows = self._db.query("SELECT id, event_id, status, attempts, last_status_code, last_error, updated_at"
                              " FROM webhook_deliveries WHERE subscription_id = ? ORDER BY updated_at DESC LIMIT ?",
                              (sub_id, limit))
        return [{"id": r["id"], "eventId": r["event_id"], "status": r["status"], "attempts": r["attempts"],
                 "lastStatusCode": r["last_status_code"], "lastError": r["last_error"],
                 "updatedAt": r["updated_at"]} for r in rows]

    @staticmethod
    def _present(row: Any) -> dict[str, Any]:
        return {"id": row["id"], "url": row["url"], "eventTypes": json.loads(row["event_types"]),
                "description": row["description"], "status": row["status"], "createdAt": row["created_at"]}
