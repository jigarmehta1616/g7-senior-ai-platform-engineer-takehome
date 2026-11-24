"""Append-only JSONL audit of every MCP tool call (allowed, denied, declined or failed).

Joined to the API's hash-chained audit log by ``correlation_id`` (sent as X-Correlation-ID).
Arguments are recorded with free text replaced by its length + SHA-256, so the audit
trail never becomes a second copy of customer data."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def fingerprint_text(text: str) -> dict[str, Any]:
    return {"chars": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()[:16]}


class ToolAuditLog:
    def __init__(self, path: str | None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []     # in-memory tail for tests / introspection
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), **fields}
        with self._lock:
            self.records.append(record)
            self.records = self.records[-500:]
            if self._path:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, default=str) + "\n")
