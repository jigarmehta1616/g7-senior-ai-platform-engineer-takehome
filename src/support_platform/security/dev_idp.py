"""A *local-only* stand-in for the corporate IdP (Okta/Entra/Auth0).

Supports two grants so the whole delegation story can be exercised offline:
  * ``urn:dev:grant-type:persona`` - mint a user token for a named persona
  * ``urn:ietf:params:oauth:grant-type:token-exchange`` (RFC 8693) - an agent exchanges
    the user's token for a down-scoped delegated token carrying an ``act`` claim.

Disabled (and the app refuses to boot with it enabled) outside ENV=local."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from support_platform.domain import errors
from support_platform.security import auth as a


@dataclass(frozen=True)
class Persona:
    subject: str
    display_name: str
    scopes: frozenset[str]
    roles: tuple[str, ...]


PERSONAS: dict[str, Persona] = {
    "support-agent": Persona("alice@example.com", "Alice (Support Engineer)",
                             frozenset({a.CUSTOMERS_READ, a.CASES_READ, a.CASES_WRITE}), ("support",)),
    "support-lead": Persona("bob@example.com", "Bob (Support Lead)",
                            frozenset({a.CUSTOMERS_READ, a.CASES_READ, a.CASES_WRITE, a.CASES_ESCALATE,
                                       a.AUDIT_READ, a.PII_READ}), ("support", "lead")),
    "finance-analyst": Persona("carol@example.com", "Carol (Finance)",
                               frozenset({a.CUSTOMERS_READ, a.CASES_READ, a.FINANCE_READ}), ("finance",)),
    "csm": Persona("erin@example.com", "Erin (Customer Success)",
                   frozenset({a.CUSTOMERS_READ, a.CASES_READ, a.PII_READ}), ("customer_success",)),
    "platform-admin": Persona("dave@example.com", "Dave (Platform Admin)",
                              frozenset({a.CUSTOMERS_READ, a.CASES_READ, a.WEBHOOKS_MANAGE, a.AUDIT_READ}),
                              ("platform",)),
}

# Agents registered with the IdP and the *maximum* scopes they may ever hold.
# Note: no finance:read / pii:read - ARR and contact details never reach an LLM.
AGENT_CLIENTS: dict[str, frozenset[str]] = {
    "support-copilot": frozenset({a.CUSTOMERS_READ, a.CASES_READ, a.CASES_WRITE, a.CASES_ESCALATE}),
}

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"  # noqa: S105
PERSONA_GRANT = "urn:dev:grant-type:persona"


class DevIdentityProvider:
    def __init__(self, secret: str, issuer: str, audience: str, verifier: a.TokenVerifier) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._verifier = verifier

    def _sign(self, claims: dict, ttl: timedelta) -> str:
        now = datetime.now(UTC)
        base = {"iss": self._issuer, "aud": self._audience, "iat": now, "nbf": now, "exp": now + ttl,
                "jti": uuid.uuid4().hex}
        return jwt.encode({**base, **claims}, self._secret, algorithm="HS256")

    def issue_persona_token(self, persona: str, ttl_minutes: int = 60) -> dict:
        p = PERSONAS.get(persona)
        if not p:
            raise errors.validation_error(f"Unknown persona '{persona}'. Known: {', '.join(PERSONAS)}")
        token = self._sign({"sub": p.subject, "scope": " ".join(sorted(p.scopes)), "client_id": "support-console",
                            "name": p.display_name, "roles": list(p.roles)}, timedelta(minutes=ttl_minutes))
        return {"access_token": token, "token_type": "Bearer", "expires_in": ttl_minutes * 60,
                "scope": " ".join(sorted(p.scopes))}

    def exchange(self, subject_token: str, actor_client: str, requested_scope: str | None,
                 ttl_minutes: int = 30) -> dict:
        user = self._verifier.verify(subject_token)
        if user.is_agent:
            raise errors.validation_error("Chained delegation is not allowed (subject_token is already delegated).")
        allowed = AGENT_CLIENTS.get(actor_client)
        if allowed is None:
            raise errors.validation_error(f"Unknown agent client '{actor_client}'.")
        requested = frozenset(requested_scope.split()) if requested_scope else allowed
        granted = user.scopes & allowed & requested
        if not granted:
            raise errors.insufficient_scope(sorted(requested))
        token = self._sign({"sub": user.subject, "scope": " ".join(sorted(granted)), "client_id": actor_client,
                            "act": {"sub": actor_client}, "roles": list(user.roles)},
                           timedelta(minutes=ttl_minutes))
        return {"access_token": token, "token_type": "Bearer", "expires_in": ttl_minutes * 60,
                "scope": " ".join(sorted(granted)),
                "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"}
