"""Tamper-evident audit log. Each row stores ``hash = sha256(prev_hash || canonical row)``
so any edit or deletion (already blocked by triggers) breaks the chain and is detected
by ``verify_chain``. In production the chain head is periodically anchored to WORM
storage (S3 Object Lock) - see SECURITY.md."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from support_platform.domain.types import Clock
from support_platform.persistence.db import Database

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    correlation_id: str
    actor_subject: str
    actor_agent: str | None
    client_id: str
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    http_status: int
    details: dict[str, Any]


def _row_digest(prev_hash: str, fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


class AuditService:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def record(self, entry: AuditEntry) -> str:
        event_id = uuid.uuid4().hex
        fields = {
            "event_id": event_id,
            "occurred_at": self._clock().isoformat(),
            "correlation_id": entry.correlation_id,
            "actor_subject": entry.actor_subject,
            "actor_agent": entry.actor_agent,
            "client_id": entry.client_id,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "outcome": entry.outcome,
            "http_status": entry.http_status,
            "details": json.dumps(entry.details, sort_keys=True, default=str),
        }
        with self._db.tx() as conn:
            last = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else GENESIS
            digest = _row_digest(prev, fields)
            conn.execute(
                "INSERT INTO audit_events (event_id, occurred_at, correlation_id, actor_subject, actor_agent,"
                " client_id, action, resource_type, resource_id, outcome, http_status, details, prev_hash, hash)"
                " VALUES (:event_id, :occurred_at, :correlation_id, :actor_subject, :actor_agent, :client_id,"
                " :action, :resource_type, :resource_id, :outcome, :http_status, :details, :prev, :hash)",
                {**fields, "prev": prev, "hash": digest},
            )
        return event_id

    def list(self, *, actor: str | None = None, agent: str | None = None, resource_id: str | None = None,
             after_seq: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[object] = []
        if actor:
            clauses.append("actor_subject = ?")
            params.append(actor)
        if agent:
            clauses.append("actor_agent = ?")
            params.append(agent)
        if resource_id:
            clauses.append("resource_id = ?")
            params.append(resource_id)
        if after_seq is not None:
            clauses.append("seq < ?")
            params.append(after_seq)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._db.query(f"SELECT * FROM audit_events {where} ORDER BY seq DESC LIMIT ?",  # noqa: S608
                              (*params, limit))
        return [dict(r) for r in rows]

    def verify_chain(self) -> tuple[bool, int]:
        prev = GENESIS
        rows = self._db.query("SELECT * FROM audit_events ORDER BY seq ASC")
        for r in rows:
            fields = {k: r[k] for k in ("event_id", "occurred_at", "correlation_id", "actor_subject", "actor_agent",
                                        "client_id", "action", "resource_type", "resource_id", "outcome",
                                        "http_status", "details")}
            if r["prev_hash"] != prev or _row_digest(prev, fields) != r["hash"]:
                return False, r["seq"]
            prev = r["hash"]
        return True, len(rows)
