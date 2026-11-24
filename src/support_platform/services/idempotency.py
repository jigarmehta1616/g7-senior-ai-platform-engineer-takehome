"""Idempotency-Key handling (draft-ietf-httpapi-idempotency-key-header).

Flow: ``begin`` atomically claims (principal, key). A completed record with the same
request hash is replayed verbatim; a different hash is a 422; an in-progress claim is a
409 (concurrent duplicate). ``complete`` stores the response; ``abandon`` releases the
claim when the operation failed so the client can retry with the same key."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from support_platform.domain import errors
from support_platform.domain.types import Clock
from support_platform.persistence.db import Database

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any
    headers: dict[str, str]


def request_fingerprint(method: str, path: str, body: Any) -> str:
    canonical = json.dumps({"m": method, "p": path, "b": body}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyService:
    def __init__(self, db: Database, clock: Clock, ttl_hours: int) -> None:
        self._db = db
        self._clock = clock
        self._ttl = timedelta(hours=ttl_hours)

    @staticmethod
    def validate_key(key: str | None) -> str:
        if not key:
            raise errors.validation_error("Idempotency-Key header is required for this operation.",
                                          [{"pointer": "header/Idempotency-Key", "detail": "required"}])
        if not KEY_PATTERN.match(key):
            raise errors.validation_error("Idempotency-Key must be 8-128 chars of [A-Za-z0-9_-:.] (a UUID is ideal).",
                                          [{"pointer": "header/Idempotency-Key", "detail": "invalid format"}])
        return key

    def begin(self, principal: str, key: str, method: str, path: str, fingerprint: str) -> StoredResponse | None:
        now = self._clock()
        with self._db.tx() as conn:
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE principal = ? AND idempotency_key = ?", (principal, key)
            ).fetchone()
            if row and row["expires_at"] <= now.isoformat():
                conn.execute("DELETE FROM idempotency_records WHERE principal = ? AND idempotency_key = ?",
                             (principal, key))
                row = None
            if row is None:
                conn.execute(
                    "INSERT INTO idempotency_records (principal, idempotency_key, method, path, request_hash, state,"
                    " created_at, expires_at) VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?)",
                    (principal, key, method, path, fingerprint, now.isoformat(), (now + self._ttl).isoformat()),
                )
                return None
        if row["request_hash"] != fingerprint:
            raise errors.idempotency_key_reused()
        if row["state"] == "in_progress":
            raise errors.idempotency_in_progress()
        return StoredResponse(row["response_status"], json.loads(row["response_body"]),
                              json.loads(row["response_headers"] or "{}"))

    def complete(self, principal: str, key: str, status: int, body: Any, headers: dict[str, str]) -> None:
        with self._db.tx() as conn:
            conn.execute(
                "UPDATE idempotency_records SET state = 'completed', response_status = ?, response_body = ?,"
                " response_headers = ? WHERE principal = ? AND idempotency_key = ?",
                (status, json.dumps(body), json.dumps(headers), principal, key),
            )

    def abandon(self, principal: str, key: str) -> None:
        with self._db.tx() as conn:
            conn.execute("DELETE FROM idempotency_records WHERE principal = ? AND idempotency_key = ?"
                         " AND state = 'in_progress'", (principal, key))

    def purge_expired(self) -> int:
        with self._db.tx() as conn:
            cur = conn.execute("DELETE FROM idempotency_records WHERE expires_at <= ?", (self._clock().isoformat(),))
            return cur.rowcount
