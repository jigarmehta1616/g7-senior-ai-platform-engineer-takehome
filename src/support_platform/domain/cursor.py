"""Opaque, signed keyset cursors.

A cursor encodes the last row's sort key + id, and a hash of the filter set. It is
HMAC-signed so clients can't forge positions, and bound to the filters so a cursor from
one query can't be replayed against another (which would silently skip/duplicate rows)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from support_platform.domain import errors


def filters_hash(filters: dict[str, Any]) -> str:
    canonical = json.dumps(filters, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class CursorCodec:
    def __init__(self, secret: str) -> None:
        self._key = secret.encode()

    def encode(self, last_key: list[Any], fhash: str) -> str:
        payload = json.dumps({"v": 1, "k": last_key, "f": fhash}, separators=(",", ":")).encode()
        sig = hmac.new(self._key, payload, hashlib.sha256).digest()[:12]
        return (base64.urlsafe_b64encode(payload).rstrip(b"=").decode() + "."
                + base64.urlsafe_b64encode(sig).rstrip(b"=").decode())

    def decode(self, cursor: str, fhash: str) -> list[Any]:
        try:
            p64, s64 = cursor.split(".", 1)
            payload = base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4))
            sig = base64.urlsafe_b64decode(s64 + "=" * (-len(s64) % 4))
        except (ValueError, TypeError) as exc:
            raise errors.invalid_cursor() from exc
        expected = hmac.new(self._key, payload, hashlib.sha256).digest()[:12]
        if not hmac.compare_digest(sig, expected):
            raise errors.invalid_cursor()
        data = json.loads(payload)
        if data.get("v") != 1 or data.get("f") != fhash or not isinstance(data.get("k"), list):
            raise errors.invalid_cursor()
        return data["k"]
