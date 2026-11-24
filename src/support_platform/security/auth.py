"""Bearer-token authentication and scope-based authorization.

Tokens are OAuth 2.0 JWT access tokens (RFC 9068 profile). Locally they are HS256 and
minted by the dev IdP; in production the verifier is swapped for RS256/ES256 + JWKS from
the corporate IdP (see SECURITY.md) - nothing else changes.

Delegation: when an AI agent acts for a user it presents a token obtained via RFC 8693
token exchange. ``sub`` is still the *human*; ``act.sub`` names the agent. Scopes are the
intersection of the user's scopes and the agent's allowed scopes, so an agent can never
exceed the person it acts for."""

from __future__ import annotations

from dataclasses import dataclass, field

import jwt

from support_platform.domain import errors

# ---- scope catalogue -------------------------------------------------------------------
CUSTOMERS_READ = "customers:read"
CASES_READ = "cases:read"
CASES_WRITE = "cases:write"
CASES_ESCALATE = "cases:escalate"
FINANCE_READ = "finance:read"     # field-level: ARR
PII_READ = "pii:read"             # field-level: customer contact details
WEBHOOKS_MANAGE = "webhooks:manage"
AUDIT_READ = "audit:read"

ALL_SCOPES = frozenset({CUSTOMERS_READ, CASES_READ, CASES_WRITE, CASES_ESCALATE, FINANCE_READ, PII_READ,
                        WEBHOOKS_MANAGE, AUDIT_READ})


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    client_id: str
    token_id: str
    actor: str | None = None          # agent identity when delegated (act.sub)
    roles: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_agent(self) -> bool:
        return self.actor is not None

    @property
    def rate_limit_key(self) -> str:
        return f"{self.subject}|{self.actor or '-'}"

    def has(self, scope: str) -> bool:
        return scope in self.scopes

    def require(self, *scopes: str) -> None:
        missing = [s for s in scopes if s not in self.scopes]
        if missing:
            raise errors.insufficient_scope(list(scopes))


class TokenVerifier:
    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token, self._secret, algorithms=["HS256"], audience=self._audience, issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]}, leeway=30,
            )
        except jwt.ExpiredSignatureError as exc:
            raise errors.unauthenticated("The access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise errors.unauthenticated("The access token is invalid.") from exc
        scopes = frozenset(str(claims.get("scope", "")).split()) & ALL_SCOPES
        act = claims.get("act") or {}
        return Principal(
            subject=str(claims["sub"]),
            scopes=scopes,
            client_id=str(claims.get("client_id", claims.get("azp", "unknown"))),
            token_id=str(claims["jti"]),
            actor=str(act["sub"]) if isinstance(act, dict) and act.get("sub") else None,
            roles=tuple(claims.get("roles", [])),
        )


def parse_bearer(header: str | None) -> str:
    if not header:
        raise errors.unauthenticated()
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise errors.unauthenticated("Use the Bearer authentication scheme.")
    return token.strip()
