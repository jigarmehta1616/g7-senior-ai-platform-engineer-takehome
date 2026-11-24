"""Contract tests: the implementation must match openapi.yaml, in both directions.

1. The spec itself is a valid OpenAPI 3.1 document.
2. Every implemented route is in the spec and every spec operation is implemented.
3. Responses (success *and* every error class) validate against the declared schemas.
4. The case.escalated webhook payload validates against the webhook schema.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute
from openapi_spec_validator import validate as validate_openapi

from tests.conftest import ANCHOR, delegated_token, set_fault
from tests.contract.spec_validator import load_spec, validate_event, validate_response

pytestmark = pytest.mark.contract


def test_spec_is_valid_openapi_31():
    validate_openapi(load_spec())


def test_routes_and_spec_do_not_drift(app):
    implemented = {
        (m.lower(), r.path)
        for router in app.state.public_routers
        for r in router.routes if isinstance(r, APIRoute) and r.include_in_schema
        for m in r.methods if m not in ("HEAD", "OPTIONS")
    }
    declared = {(m, p) for p, ops in load_spec()["paths"].items() for m in ops if m in ("get", "post", "delete")}
    assert implemented == declared, {"missing_in_spec": implemented - declared,
                                     "not_implemented": declared - implemented}


def test_every_operation_declares_problem_errors():
    for path, ops in load_spec()["paths"].items():
        for method, op in ops.items():
            if op.get("security") == []:
                continue
            for code in ("401", "403", "429"):
                assert code in op["responses"], f"{method.upper()} {path} missing {code}"


@pytest.fixture
def check(client):
    """Send a request and assert the response conforms to the contract."""
    def _send(method: str, url: str, **kw):
        resp = client.request(method, url, **kw)
        validate_response(resp)
        assert "x-correlation-id" in resp.headers
        return resp
    return _send


def test_customer_endpoint_conforms(check, auth, mock_app):
    assert check("GET", "/v1/customers/ACC-007", headers=auth("finance-analyst")).status_code == 200
    assert check("GET", "/v1/customers/ACC-007", headers=auth("support-agent")).status_code == 200
    assert check("GET", "/v1/customers/NOPE-1", headers=auth("support-agent")).status_code == 404
    assert check("GET", "/v1/customers/bad%20id", headers=auth("support-agent")).status_code == 400
    assert check("GET", "/v1/customers/ACC-007").status_code == 401
    assert check("GET", "/v1/customers/ACC-007", headers=auth("platform-admin") | {}).status_code == 200
    set_fault(mock_app, "usage", "error")
    assert check("GET", "/v1/customers/ACC-007", headers=auth("support-agent")).json()["degraded"] is True


def test_case_endpoints_conform(check, auth):
    h = auth("support-lead")
    page = check("GET", "/v1/cases?priority=P1&supportTier=Platinum&include=account&limit=2", headers=h).json()
    check("GET", f"/v1/cases?priority=P1&supportTier=Platinum&include=account&limit=2&cursor={page['page']['nextCursor']}",
          headers=h)
    check("GET", "/v1/cases?limit=1000", headers=h)
    check("GET", "/v1/cases?status=bogus", headers=h)
    check("GET", "/v1/cases?cursor=forged.cursor", headers=h)
    check("GET", "/v1/cases?account_id=ACC-007", headers=h)
    detail = check("GET", "/v1/cases/CS-10231", headers=h)
    assert check("GET", "/v1/cases/CS-10231", headers=h | {"If-None-Match": detail.headers["etag"]}).status_code == 304
    check("GET", "/v1/cases/CS-99999", headers=h)
    check("GET", "/v1/cases", headers=auth("platform-admin") | {"Authorization": "Bearer nope"})


def test_write_endpoints_conform(check, auth):
    h = auth("support-lead")
    key = {"Idempotency-Key": str(uuid.uuid4())}
    check("POST", "/v1/cases/CS-10231/comments", headers=h | key, json={"body": "Contract check"})
    check("POST", "/v1/cases/CS-10231/comments", headers=h | key, json={"body": "Contract check"})       # replay
    check("POST", "/v1/cases/CS-10231/comments", headers=h | key, json={"body": "Different"})            # 422
    check("POST", "/v1/cases/CS-10231/comments", headers=h, json={"body": "no key"})                     # 400
    check("POST", "/v1/cases/CS-10231/comments", headers=h | {"Idempotency-Key": str(uuid.uuid4())},
          json={"body": "", "extra": 1})                                                                 # 400
    check("POST", "/v1/cases/CS-10231/comments", headers=auth("csm") | key, json={"body": "x"})          # 403

    etag = check("GET", "/v1/cases/CS-10240", headers=h).headers["etag"]
    check("POST", "/v1/cases/CS-10240/escalate", headers=h, json={"reason": "customer_impact"})          # 428
    check("POST", "/v1/cases/CS-10240/escalate", headers=h | {"If-Match": '"v999"'},
          json={"reason": "customer_impact"})                                                            # 412
    check("POST", "/v1/cases/CS-10240/escalate", headers=h | {"If-Match": etag},
          json={"reason": "customer_impact"})                                                            # 200
    check("POST", "/v1/cases/CS-10290/escalate", headers=h | {"If-Match": '"v2"'},
          json={"reason": "customer_impact"})                                                            # 409
    check("POST", "/v1/cases/CS-10301/escalate", headers=h | {"If-Match": '"v1"'},
          json={"reason": "customer_impact"})                                                            # 422
    check("POST", "/v1/cases/CS-10240/escalate", headers=auth("support-agent") | {"If-Match": etag},
          json={"reason": "customer_impact"})                                                            # 403


def test_governance_and_ops_endpoints_conform(check, auth):
    admin = auth("platform-admin")
    created = check("POST", "/v1/webhook-subscriptions", headers=admin,
                    json={"url": "https://hooks.example.com/x", "eventTypes": ["case.escalated"]})
    sub_id = created.json()["id"]
    check("GET", "/v1/webhook-subscriptions", headers=admin)
    check("GET", f"/v1/webhook-subscriptions/{sub_id}/deliveries", headers=admin)
    check("DELETE", f"/v1/webhook-subscriptions/{sub_id}", headers=admin)
    check("POST", "/v1/webhook-subscriptions", headers=admin, json={"url": "https://x.example.com", "eventTypes": ["nope"]})
    check("GET", "/v1/audit-events", headers=admin)
    check("GET", "/v1/audit-events", headers=auth("support-agent"))
    check("GET", "/healthz")
    check("GET", "/readyz")


def test_agent_delegated_calls_conform(client, check):
    token = delegated_token(client, "support-lead")
    h = {"Authorization": f"Bearer {token}"}
    body = check("GET", "/v1/customers/ACC-007", headers=h).json()
    assert "arrUsd" not in body["contract"] and "contract.arrUsd" in body["redactedFields"]


def test_webhook_event_conforms_to_spec(client, auth, app, mock_app):
    import anyio

    h = auth("support-lead")
    etag = client.get("/v1/cases/CS-10231", headers=h).headers["etag"]
    assert client.post("/v1/cases/CS-10231/escalate", headers=h | {"If-Match": etag},
                       json={"reason": "sla_breach_risk"}).status_code == 200
    c = app.state.container

    async def pump():
        await c.relay.publish_pending()
        await c.dispatcher.deliver_due()
    client.portal.call(pump) if hasattr(client, "portal") and client.portal else anyio.run(pump)
    received = mock_app.state.mock.received_webhooks
    assert received and received[-1]["verified"] is True
    validate_event(received[-1]["event"])
    assert received[-1]["event"]["time"].startswith(ANCHOR.date().isoformat())
