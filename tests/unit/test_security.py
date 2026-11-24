import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from support_platform.domain.errors import ProblemError
from support_platform.security import auth
from support_platform.security.dev_idp import DevIdentityProvider
from support_platform.security.webhook_signing import (
    WebhookVerificationError,
    generate_secret,
    signed_headers,
    verify_webhook,
)

SECRET, ISS, AUD = "s" * 40, "https://idp.test", "api"


@pytest.fixture
def idp():
    verifier = auth.TokenVerifier(SECRET, ISS, AUD)
    return DevIdentityProvider(SECRET, ISS, AUD, verifier), verifier


def test_persona_token_roundtrip(idp):
    provider, verifier = idp
    p = verifier.verify(provider.issue_persona_token("finance-analyst")["access_token"])
    assert p.subject == "carol@example.com" and p.has(auth.FINANCE_READ) and not p.is_agent


def test_token_exchange_downscopes_to_user_and_agent_intersection(idp):
    provider, verifier = idp
    lead = provider.issue_persona_token("support-lead")["access_token"]
    delegated = verifier.verify(provider.exchange(lead, "support-copilot", None)["access_token"])
    assert delegated.subject == "bob@example.com" and delegated.actor == "support-copilot"
    assert auth.CASES_ESCALATE in delegated.scopes
    assert auth.PII_READ not in delegated.scopes and auth.AUDIT_READ not in delegated.scopes

    finance = provider.issue_persona_token("finance-analyst")["access_token"]
    d2 = verifier.verify(provider.exchange(finance, "support-copilot", None)["access_token"])
    assert auth.FINANCE_READ not in d2.scopes          # agent can never hold finance:read
    assert auth.CASES_ESCALATE not in d2.scopes        # nor more than the user


def test_chained_delegation_and_unknown_agents_rejected(idp):
    provider, _ = idp
    lead = provider.issue_persona_token("support-lead")["access_token"]
    delegated = provider.exchange(lead, "support-copilot", None)["access_token"]
    with pytest.raises(ProblemError):
        provider.exchange(delegated, "support-copilot", None)
    with pytest.raises(ProblemError):
        provider.exchange(lead, "rogue-agent", None)


@pytest.mark.parametrize("mutate", [
    lambda c: {**c, "exp": datetime.now(UTC) - timedelta(minutes=5)},
    lambda c: {**c, "aud": "other-api"},
    lambda c: {**c, "iss": "https://evil"},
])
def test_invalid_tokens_rejected(mutate):
    now = datetime.now(UTC)
    claims = {"sub": "x", "iss": ISS, "aud": AUD, "iat": now, "exp": now + timedelta(minutes=5), "jti": "1",
              "scope": "cases:read"}
    token = jwt.encode(mutate(claims), SECRET, algorithm="HS256")
    with pytest.raises(ProblemError) as ei:
        auth.TokenVerifier(SECRET, ISS, AUD).verify(token)
    assert ei.value.status == 401


def test_alg_none_and_wrong_key_rejected():
    now = datetime.now(UTC)
    claims = {"sub": "x", "iss": ISS, "aud": AUD, "iat": now, "exp": now + timedelta(minutes=5), "jti": "1"}
    for token in (jwt.encode(claims, "wrong-key-" * 4, algorithm="HS256"),
                  jwt.encode(claims, None, algorithm="none")):
        with pytest.raises(ProblemError):
            auth.TokenVerifier(SECRET, ISS, AUD).verify(token)


def test_unknown_scopes_are_dropped():
    now = datetime.now(UTC)
    token = jwt.encode({"sub": "x", "iss": ISS, "aud": AUD, "iat": now, "exp": now + timedelta(minutes=5),
                        "jti": "1", "scope": "cases:read admin:everything"}, SECRET, algorithm="HS256")
    assert auth.TokenVerifier(SECRET, ISS, AUD).verify(token).scopes == {"cases:read"}


# ---- webhooks --------------------------------------------------------------------------

def test_webhook_sign_verify_and_rotation():
    old, new = generate_secret(), generate_secret()
    body = b'{"type":"case.escalated"}'
    h = signed_headers(new, "evt_1", body)
    verify_webhook(new, h, body)
    rotated = {**h, "webhook-signature": signed_headers(old, "evt_1", body, int(h["webhook-timestamp"]))
               ["webhook-signature"] + " " + h["webhook-signature"]}
    verify_webhook(new, rotated, body)


@pytest.mark.parametrize("tamper", ["body", "id", "old_timestamp", "missing"])
def test_webhook_verification_failures(tamper):
    secret = generate_secret()
    body = b'{"a":1}'
    ts = int(time.time())
    h = signed_headers(secret, "evt_1", body, ts)
    if tamper == "body":
        body = b'{"a":2}'
    elif tamper == "id":
        h["webhook-id"] = "evt_2"
    elif tamper == "old_timestamp":
        h = signed_headers(secret, "evt_1", body, ts - 3600)
    else:
        h.pop("webhook-signature")
    with pytest.raises(WebhookVerificationError):
        verify_webhook(secret, h, body)


# ---- logging -----------------------------------------------------------------------------

def test_client_reset_noise_is_filtered_but_real_errors_are_not():
    import logging

    from support_platform.observability.logging import ClientResetFilter

    def record(name: str, msg: str, exc: BaseException) -> logging.LogRecord:
        return logging.LogRecord(name, logging.ERROR, __file__, 1, msg, None, (type(exc), exc, None))

    f = ClientResetFilter()
    assert not f.filter(record("asyncio", "Exception in callback _call_connection_lost()", ConnectionResetError()))
    assert f.filter(record("asyncio", "Task exception was never retrieved", RuntimeError()))
    assert f.filter(record("support_platform", "Exception in callback _call_connection_lost()", ConnectionResetError()))
