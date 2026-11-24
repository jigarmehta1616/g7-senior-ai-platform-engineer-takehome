"""Webhook signing and verification following the Standard Webhooks spec
(https://www.standardwebhooks.com): HMAC-SHA256 over ``{id}.{timestamp}.{body}``.

Headers: ``webhook-id``, ``webhook-timestamp`` (unix seconds), ``webhook-signature``
(space-separated ``v1,<base64>`` entries - more than one during secret rotation).

Receivers MUST: verify with a constant-time compare, reject timestamps outside the
tolerance window (replay protection), and de-duplicate on ``webhook-id``."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

DEFAULT_TOLERANCE_S = 300


class WebhookVerificationError(Exception):
    pass


def generate_secret() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()


def _key(secret: str) -> bytes:
    raw = secret.removeprefix("whsec_")
    return base64.b64decode(raw)


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    to_sign = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(_key(secret), to_sign, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def signed_headers(secret: str, msg_id: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = int(time.time()) if timestamp is None else timestamp
    return {"webhook-id": msg_id, "webhook-timestamp": str(ts), "webhook-signature": sign(secret, msg_id, ts, body)}


def verify_webhook(secret: str, headers: dict[str, str], body: bytes, *, tolerance_s: int = DEFAULT_TOLERANCE_S,
                   now: int | None = None) -> None:
    h = {k.lower(): v for k, v in headers.items()}
    msg_id, ts_raw, sig_header = h.get("webhook-id"), h.get("webhook-timestamp"), h.get("webhook-signature")
    if not (msg_id and ts_raw and sig_header):
        raise WebhookVerificationError("missing webhook headers")
    try:
        ts = int(ts_raw)
    except ValueError as exc:
        raise WebhookVerificationError("bad timestamp") from exc
    current = int(time.time()) if now is None else now
    if abs(current - ts) > tolerance_s:
        raise WebhookVerificationError("timestamp outside tolerance")
    expected = sign(secret, msg_id, ts, body)
    for candidate in sig_header.split():
        if hmac.compare_digest(candidate, expected):
            return
    raise WebhookVerificationError("no matching signature")
