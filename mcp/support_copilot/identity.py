"""Who the agent is acting for.

The server refuses to start with a token that is not a *delegated* token (no ``act``
claim): the Copilot must never run with a human's raw token or a service super-user token.
Signature verification is the API's job; here we only read claims for audit labelling."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass


class IdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class DelegatedIdentity:
    user: str
    agent: str
    scopes: frozenset[str]

    @property
    def key(self) -> str:
        return f"{self.user}|{self.agent}"


def read_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as exc:
        raise IdentityError("COPILOT_ACCESS_TOKEN is not a JWT") from exc


def identity_from_token(token: str) -> DelegatedIdentity:
    claims = read_claims(token)
    act = claims.get("act") or {}
    if not isinstance(act, dict) or not act.get("sub"):
        raise IdentityError("Refusing to start: the token is not a delegated (RFC 8693) token. Obtain one via "
                            "token exchange so the agent acts on behalf of a user, never as one.")
    return DelegatedIdentity(user=str(claims.get("sub")), agent=str(act["sub"]),
                             scopes=frozenset(str(claims.get("scope", "")).split()))
