"""End-to-end behaviour of the API against the mock upstreams (in-process)."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_upstreams.app import create_mock_app
from support_platform.api.app import create_app
from tests.conftest import ANCHOR, delegated_token, make_settings, set_fault

pytestmark = pytest.mark.integration
SAMPLE_QUESTION = {"priority": "P1", "status": "open,in_progress,pending_customer", "supportTier": "Platinum",
                   "openedBefore": "2026-11-22T12:00:00Z", "renewalBefore": "2027-02-22", "include": "account"}


# ---- aggregated customer view ------------------------------------------------------------

def test_customer_aggregate_happy_path(client, auth):
    body = client.get("/v1/customers/ACC-007", headers=auth("support-agent")).json()
    assert body["supportTier"] == "Platinum" and body["contract"]["renewalInDays"] == 52
    assert body["usage"]["latestMonth"] == "2026-10" and body["usage"]["protectedTbTrend"] == "up"
    assert body["cases"] == {"active": 2, "activeP1": 1, "escalated": 0}
    assert body["degraded"] is False


@pytest.mark.parametrize(("persona", "arr_visible", "pii_visible"), [
    ("finance-analyst", True, False), ("support-agent", False, False), ("csm", False, True),
])
def test_field_level_authorization(client, auth, persona, arr_visible, pii_visible):
    body = client.get("/v1/customers/ACC-007", headers=auth(persona)).json()
    assert ("arrUsd" in body["contract"]) is arr_visible
    assert ("primaryContact" in body) is pii_visible
    assert ("contract.arrUsd" in body["redactedFields"]) is not arr_visible


def test_usage_down_returns_entitlement_with_degraded_flag(client, auth, mock_app):
    set_fault(mock_app, "usage", "error")
    r = client.get("/v1/customers/ACC-007", headers=auth("support-agent"))
    body = r.json()
    assert r.status_code == 200 and body["degraded"] is True and body["usage"] is None
    assert body["supportTier"] == "Platinum"
    usage_src = next(s for s in body["dataSources"] if s["source"] == "usage")
    assert usage_src == {"source": "usage", "status": "unavailable", "reason": "unavailable"}


def test_usage_timeout_is_bounded_and_degrades(client, auth, mock_app):
    set_fault(mock_app, "usage", "timeout")
    r = client.get("/v1/customers/ACC-007", headers=auth("support-agent"))
    assert r.status_code == 200
    assert next(s for s in r.json()["dataSources"] if s["source"] == "usage")["reason"] == "timeout"


def test_flaky_upstream_recovers_via_retry(client, auth, mock_app):
    set_fault(mock_app, "usage", "flaky", fail_next=2)
    body = client.get("/v1/customers/ACC-007", headers=auth("support-agent")).json()
    assert body["degraded"] is False and body["usage"] is not None


def test_circuit_opens_and_stops_calling_failing_upstream(client, auth, mock_app):
    set_fault(mock_app, "usage", "error")
    h = auth("support-agent")
    client.get("/v1/customers/ACC-007", headers=h)        # 3 attempts -> threshold 3 -> open
    calls_before = mock_app.state.mock.calls["usage"]
    for _ in range(3):
        body = client.get("/v1/customers/ACC-007", headers=h).json()
        assert next(s for s in body["dataSources"] if s["source"] == "usage")["reason"] == "circuit_open"
    assert mock_app.state.mock.calls["usage"] == calls_before
    assert client.get("/readyz").json()["upstreams"]["usage"] == "open"


def test_entitlements_down_serves_stale_snapshot(client, auth, mock_app):
    set_fault(mock_app, "entitlements", "error")
    body = client.get("/v1/customers/ACC-007", headers=auth("support-agent")).json()
    ent = next(s for s in body["dataSources"] if s["source"] == "entitlements")
    assert ent["status"] == "stale" and body["degraded"] is True and body["name"] == "Globex Industries"


def test_entitlements_down_without_snapshot_is_503(tmp_path: Path):
    mock = create_mock_app(rebase_time=False)
    set_fault(mock, "entitlements", "error")           # snapshot refresh at start-up fails too
    app = create_app(make_settings(tmp_path), clock=lambda: ANCHOR,
                     upstream_transport=httpx.ASGITransport(app=mock), run_background=False)
    with TestClient(app) as c:
        token = c.post("/dev/oauth/token", data={"grant_type": "urn:dev:grant-type:persona",
                                                 "persona": "support-agent"}).json()["access_token"]
        r = c.get("/v1/customers/ACC-007", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503 and r.json()["upstream"] == "entitlements" and "retry-after" in r.headers


# ---- case search -------------------------------------------------------------------------

def test_sample_question_filters(client, auth):
    body = client.get("/v1/cases", params=SAMPLE_QUESTION, headers=auth("support-agent")).json()
    accounts = {c["account"]["name"] for c in body["data"]}
    assert accounts == {"Globex Industries", "Acme Corp", "Stark Logistics", "Tyrell Robotics"}
    assert all(c["priority"] == "P1" and c["ageHours"] > 48 for c in body["data"])


def test_cursor_pagination_is_complete_and_stable(client, auth):
    h = auth("support-agent")
    seen, cursor = [], None
    while True:
        params = {"limit": 3, "sort": "priority"} | ({"cursor": cursor} if cursor else {})
        page = client.get("/v1/cases", params=params, headers=h).json()
        seen += [c["id"] for c in page["data"]]
        cursor = page["page"]["nextCursor"]
        if not cursor:
            break
    full = client.get("/v1/cases", params={"limit": 100, "sort": "priority"}, headers=h).json()["data"]
    assert seen == [c["id"] for c in full] and len(seen) == len(set(seen)) == 16
    priorities = [c["priority"] for c in full]
    assert priorities == sorted(priorities)


def test_cursor_cannot_be_replayed_with_other_filters(client, auth):
    h = auth("support-agent")
    cursor = client.get("/v1/cases?limit=2", headers=h).json()["page"]["nextCursor"]
    r = client.get(f"/v1/cases?limit=2&priority=P1&cursor={cursor}", headers=h)
    assert r.status_code == 400 and r.json()["type"].endswith("/invalid-cursor")


def test_validation_errors_are_problem_json_with_pointers(client, auth):
    r = client.get("/v1/cases?limit=0&openedBefore=2026-11-01T00:00:00", headers=auth("support-agent"))
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/problem+json")
    assert any(e["pointer"] == "query/limit" for e in r.json()["errors"])


def test_naive_timestamp_rejected(client, auth):
    r = client.get("/v1/cases?openedBefore=2026-11-01T00:00:00", headers=auth("support-agent"))
    assert r.status_code == 400 and r.json()["errors"][0]["pointer"] == "query/openedBefore"


def test_deprecated_param_still_works_and_signals_deprecation(client, auth):
    r = client.get("/v1/cases?account_id=ACC-007", headers=auth("support-agent"))
    assert r.status_code == 200 and {c["accountId"] for c in r.json()["data"]} == {"ACC-007"}
    assert r.headers["deprecation"] and r.headers["sunset"] and 'rel="deprecation"' in r.headers["link"]


# ---- comments ----------------------------------------------------------------------------

def test_comment_is_idempotent_and_author_comes_from_token(client, auth, mock_app):
    h = auth("support-agent") | {"Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/v1/cases/CS-10232/comments", headers=h, json={"body": "Looking into it"})
    again = client.post("/v1/cases/CS-10232/comments", headers=h, json={"body": "Looking into it"})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() and again.headers["idempotency-replayed"] == "true"
    assert first.json()["author"] == "alice@example.com"
    assert len(mock_app.state.mock.cases["CS-10232"]["Comments"]) == 1


def test_comment_author_cannot_be_spoofed(client, auth):
    r = client.post("/v1/cases/CS-10232/comments", headers=auth("support-agent") | {"Idempotency-Key": "k-12345678"},
                    json={"body": "x", "author": "ceo@example.com"})
    assert r.status_code == 400


def test_comment_on_missing_case_is_404_and_key_is_released(client, auth):
    h = auth("support-agent") | {"Idempotency-Key": "missing-case-key"}
    assert client.post("/v1/cases/CS-99999/comments", headers=h, json={"body": "x"}).status_code == 404
    assert client.post("/v1/cases/CS-99999/comments", headers=h, json={"body": "x"}).status_code == 404


def test_upstream_failure_on_comment_releases_key_for_retry(client, auth, mock_app):
    h = auth("support-agent") | {"Idempotency-Key": "retry-after-outage"}
    set_fault(mock_app, "cases", "error")
    assert client.post("/v1/cases/CS-10232/comments", headers=h, json={"body": "x"}).status_code == 503
    set_fault(mock_app, "cases", "ok")
    client.app.state.container.breakers["cases"].record_success()
    assert client.post("/v1/cases/CS-10232/comments", headers=h, json={"body": "x"}).status_code == 201


def test_agent_comment_is_attributed_to_user_via_agent(client):
    h = {"Authorization": f"Bearer {delegated_token(client, 'support-agent')}", "Idempotency-Key": "agent-key-1"}
    r = client.post("/v1/cases/CS-10232/comments", headers=h, json={"body": "Drafted by copilot"})
    assert r.json()["author"] == "alice@example.com via support-copilot"


# ---- escalation + webhook ----------------------------------------------------------------

def test_escalation_flow_with_etag_event_and_signed_webhook(client, auth, mock_app):
    h = auth("support-lead")
    etag = client.get("/v1/cases/CS-10231", headers=h).headers["etag"]
    r = client.post("/v1/cases/CS-10231/escalate", headers=h | {"If-Match": etag},
                    json={"reason": "sla_breach_risk", "note": "Renewal at risk"})
    assert r.status_code == 200
    assert r.json()["escalation"] == {"level": 1, "targetTeam": "engineering_on_call", "reason": "sla_breach_risk"}
    assert r.headers["etag"] != etag

    stale = client.post("/v1/cases/CS-10231/escalate", headers=h | {"If-Match": etag},
                        json={"reason": "sla_breach_risk"})
    assert stale.status_code == 412 and stale.headers["etag"] == r.headers["etag"]

    c = client.app.state.container

    async def pump():
        await c.relay.publish_pending()
        await c.dispatcher.deliver_due()
    client.portal.call(pump)
    [delivery] = mock_app.state.mock.received_webhooks
    assert delivery["verified"] is True
    data = delivery["event"]["data"]
    assert data["caseId"] == "CS-10231" and data["escalatedBy"] == {"subject": "bob@example.com", "agent": None}
    assert "Renewal at risk" not in str(delivery["event"])        # free text is not broadcast


def test_failed_webhook_is_retried_with_backoff_then_dead_lettered(client, auth, settings):
    c = client.app.state.container
    admin = auth("platform-admin")
    created = client.post("/v1/webhook-subscriptions", headers=admin,
                          json={"url": "http://upstream/does-not-exist", "eventTypes": ["case.escalated"]}).json()
    h = auth("support-lead")
    etag = client.get("/v1/cases/CS-10240", headers=h).headers["etag"]
    client.post("/v1/cases/CS-10240/escalate", headers=h | {"If-Match": etag}, json={"reason": "customer_impact"})
    client.portal.call(c.relay.publish_pending)
    client.portal.call(c.dispatcher.deliver_due)
    [d] = client.get(f"/v1/webhook-subscriptions/{created['id']}/deliveries", headers=admin).json()["data"]
    assert d["status"] == "pending" and d["attempts"] == 1 and d["lastStatusCode"] == 404
    c.db.query("UPDATE webhook_deliveries SET attempts = ?, next_attempt_at = '2000-01-01'",
               (settings.webhook_max_attempts - 1,))
    client.portal.call(c.dispatcher.deliver_due)
    [d] = client.get(f"/v1/webhook-subscriptions/{created['id']}/deliveries", headers=admin).json()["data"]
    assert d["status"] == "dead"


def test_scope_required_for_escalation(client, auth):
    r = client.post("/v1/cases/CS-10231/escalate", headers=auth("support-agent") | {"If-Match": '"v3"'},
                    json={"reason": "customer_impact"})
    assert r.status_code == 403 and r.json()["requiredScopes"] == ["cases:escalate"]


# ---- cross-cutting -----------------------------------------------------------------------

def test_agent_rate_limit_is_tighter_and_returns_retry_after(tmp_path, mock_app):
    app = create_app(make_settings(tmp_path, rate_limit_agent_per_min=2), clock=lambda: ANCHOR,
                     upstream_transport=httpx.ASGITransport(app=mock_app), run_background=False)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {delegated_token(c, 'support-agent')}"}
        statuses = [c.get("/v1/cases/CS-10231", headers=h) for _ in range(3)]
    assert [s.status_code for s in statuses] == [200, 200, 429]
    assert statuses[0].headers["ratelimit-limit"] == "2" and int(statuses[2].headers["retry-after"]) >= 1


def test_audit_log_captures_agent_reads_mutations_and_denials(client, auth):
    agent_h = {"Authorization": f"Bearer {delegated_token(client, 'support-agent')}", "X-Agent-Tool": "search_cases"}
    client.get("/v1/cases?limit=1", headers=agent_h)
    client.get("/v1/cases?limit=1", headers=auth("support-agent"))          # human read: not audited
    client.post("/v1/cases/CS-10231/escalate", headers=auth("support-agent") | {"If-Match": '"v3"'},
                json={"reason": "customer_impact"})                         # denied
    events = client.get("/v1/audit-events", headers=auth("support-lead")).json()
    actions = [(e["action"], e["outcome"], e["actor"]["agent"]) for e in events["data"]]
    assert ("GET /v1/cases", "success", "support-copilot") in actions
    assert ("POST /v1/cases/{caseId}/escalate", "denied", None) in actions
    assert sum(1 for a in actions if a[0] == "GET /v1/cases") == 1
    assert events["integrity"]["chainValid"] is True


def test_correlation_id_is_echoed_or_generated(client, auth):
    r = client.get("/v1/cases/CS-10231", headers=auth("support-agent") | {"X-Correlation-ID": "trace-abc-123"})
    assert r.headers["x-correlation-id"] == "trace-abc-123"
    r = client.get("/v1/cases/CS-10231", headers=auth("support-agent") | {"X-Correlation-ID": "bad id\n<script>"})
    assert r.headers["x-correlation-id"] != "bad id\n<script>" and len(r.headers["x-correlation-id"]) == 32


def test_oversized_body_rejected(client, auth):
    r = client.post("/v1/cases/CS-10231/comments", headers=auth("support-agent") | {"Idempotency-Key": "big-body-1"},
                    content=b'{"body":"' + b"x" * 70_000 + b'"}')
    assert r.status_code == 413


def test_security_headers_present(client, auth):
    r = client.get("/v1/cases/CS-10231", headers=auth("support-agent"))
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"


def test_refuses_to_boot_with_dev_secrets_outside_local(tmp_path):
    with pytest.raises(RuntimeError):
        make_settings(tmp_path, env="prod").validate()
