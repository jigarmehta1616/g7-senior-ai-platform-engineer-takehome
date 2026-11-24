"""Structured JSON logging with a correlation ID carried in a ContextVar so every log line
emitted while serving a request (including upstream calls and webhook enqueues) can be
joined across the API, the MCP server audit trail and downstream systems."""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_VALID_CID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def accept_or_create_correlation_id(incoming: str | None) -> str:
    """Accept a caller-supplied ID only if it is well-formed (prevents log injection)."""
    if incoming and _VALID_CID.match(incoming):
        return incoming
    return new_correlation_id()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ClientResetFilter(logging.Filter):
    """Drop asyncio's 'connection reset by peer' noise on Windows (CPython Proactor loop).

    When a client closes a keep-alive socket abruptly, the Proactor event loop logs a
    ConnectionResetError from ``_call_connection_lost`` at ERROR level. It isn't an application
    error and doesn't occur on Linux. Only that exact record is dropped; every other asyncio
    error still gets through."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not (record.name == "asyncio" and isinstance(exc, ConnectionResetError)
                    and "_call_connection_lost" in record.getMessage())


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ClientResetFilter())
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
