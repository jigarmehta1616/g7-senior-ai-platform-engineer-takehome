"""Edge cases across the HTTP surface. Every response here must also match openapi.yaml."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from support_platform.api.app import create_app
from tests.conftest import ANCHOR, make_settings, set_fault
from tests.contract.spec_validator import validate_response

pytestmark = pytest.mark.integration


@pytest.fixture
def send(client):
    """Send a request, assert it matches the contract and is problem+json when it's an error."""
    def _send(method: str, url: str, **kw):
        resp = client.request(method, url, **kw)
        if url.startswith("/v1/") or url in ("/healthz", "/readyz"):
            validate_response(resp)
        if resp.status_code >= 400:
            assert resp.headers["content-type"].startswith("application/problem+json"), resp.text
            body = resp.json()
            assert body["status"] == resp.status_code and body["correlationId"]
        return resp
    return _send


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


# ---- authentication --------------------------------------------------------------------

@pytest.mark.parametrize("header", [
    "Bearer", "Bearer ", "Basic dXNlcjpwYXNz", "bearer not-a-jwt", "Token abc", "Bearer a.b.c",
])
def test_malformed_auth_headers_are_401(send, header):
    assert send("GET", "/v1/cases", headers={"Authorization": header}).status_code == 401


def test_expired_token_is_401(send, settings):
    now = datetime.now(UTC)
    token = jwt.encode({"sub": "x", "iss": settings.jwt_issuer, "aud": settings.jwt_audience, "iat": now - timedelta(hours=2),
                        "exp": now - timedelta(hours=1), "jti": "1", "scope": "cases:read"},
                       settings.jwt_secret, algorithm="HS256")
    r = send("GET", "/v1/cases", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


# ---- request bodies --------------------------------------------------------------------

@pytest.mark.parametrize("content", [b"{not json", b"", b"[]", b'"just a string"', b"null"])
def test_malformed_or_wrong_shaped_bodies_are_400(send, auth, content):
    r = send("POST", "/v1/cases/CS-10232/comments", content=content,
             headers=auth("support-agent") | key() | {"Content-Type": "application/json"})
    assert r.status_code == 400


@pytest.mark.parametrize("body", [
    {"body": ""}, {"body": "   "}, {"body": "\n\t"}, {"body": "x" * 4001},
    {"body": "ok", "visibility": "everyone"}, {"body": 123}, {"body": None},
])
def test_invalid_comment_bodies_are_400(send, auth, body):
    assert send("POST", "/v1/cases/CS-10232/comments", json=body, headers=auth("support-agent") | key()).status_code == 400


def test_unicode_and_markup_in_comments_are_stored_verbatim(send, auth):
    text = "Löschung bestätigt ✅ — <script>alert(1)</script> 日本語"
    r = send("POST", "/v1/cases/CS-10232/comments", json={"body": text}, headers=auth("support-agent") | key())
    assert r.status_code == 201 and r.json()["body"] == text


def test_comment_at_exact_max_length_is_accepted(send, auth):
    r = send("POST", "/v1/cases/CS-10232/comments", json={"body": "x" * 4000}, headers=auth("support-agent") | key())
    assert r.status_code == 201


@pytest.mark.parametrize("idem", ["short", "x" * 129, "has space here", "bad/char"])
def test_invalid_idempotency_keys_are_400(send, auth, idem):
    r = send("POST", "/v1/cases/CS-10232/comments", json={"body": "x"},
             headers=auth("support-agent") | {"Idempotency-Key": idem})
    assert r.status_code == 400


@pytest.mark.parametrize("body", [
    {}, {"reason": "because"}, {"reason": "other", "note": "   "}, {"reason": "customer_impact", "note": "n" * 501},
    {"reason": "customer_impact", "extra": True},
])
def test_invalid_escalation_bodies(send, auth, body):
    etag = send("GET", "/v1/cases/CS-10231", headers=auth("support-lead")).headers["etag"]
    r = send("POST", "/v1/cases/CS-10231/escalate", json=body, headers=auth("support-lead") | {"If-Match": etag})
    assert r.status_code in (400, 422)


def test_weak_etag_is_accepted_for_escalation(send, auth):
    etag = send("GET", "/v1/cases/CS-10231", headers=auth("support-lead")).headers["etag"]
    r = send("POST", "/v1/cases/CS-10231/escalate", json={"reason": "customer_impact"},
             headers=auth("support-lead") | {"If-Match": f"W/{etag}"})
    assert r.status_code == 200


def test_escalating_to_level_two_then_limit(send, auth):
    h = auth("support-lead")
    for expected in (200, 200, 409):
        etag = send("GET", "/v1/cases/CS-10240", headers=h).headers["etag"]
        r = send("POST", "/v1/cases/CS-10240/escalate", json={"reason": "customer_impact"}, headers=h | {"If-Match": etag})
        assert r.status_code == expected
    assert r.json()["code"] == "ESCALATION_LIMIT_REACHED"


# ---- query parameters ------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "limit=abc", "limit=0", "limit=101", "sort=random", "priority=P9", "status=open,nope", "supportTier=Diamond",
    "renewalBefore=2027-13-01", "openedBefore=yesterday", "include=everything", "accountId=bad%20id",
    "cursor=" + "x" * 600,
])
def test_invalid_query_parameters_are_400(send, auth, query):
    assert send("GET", f"/v1/cases?{query}", headers=auth("support-agent")).status_code == 400


@pytest.mark.parametrize("query", ["priority=P1,,P2", "priority=P1,P1", "status=", "priority= P1 "])
def test_tolerant_list_parameters(send, auth, query):
    assert send("GET", f"/v1/cases?{query}", headers=auth("support-agent")).status_code == 200


def test_empty_result_and_inverted_time_window(send, auth):
    r = send("GET", "/v1/cases?openedAfter=2030-01-01T00:00:00Z&openedBefore=2020-01-01T00:00:00Z",
             headers=auth("support-agent"))
    assert r.status_code == 200 and r.json()["data"] == [] and r.json()["page"]["nextCursor"] is None


def test_unknown_account_filter_returns_empty_not_error(send, auth):
    r = send("GET", "/v1/cases?accountId=ACC-NOPE", headers=auth("support-agent"))
    assert r.status_code == 200 and r.json()["data"] == []


# ---- routing ---------------------------------------------------------------------------

def test_unknown_route_and_wrong_method_are_problem_json(client, auth):
    for method, url, status in (("GET", "/v1/nope", 404), ("PUT", "/v1/cases/CS-10231", 405),
                                ("DELETE", "/v1/cases/CS-10231", 405)):
        r = client.request(method, url, headers=auth("support-agent"))
        assert r.status_code == status
        assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("path", ["/v1/cases/cs-10231", "/v1/cases/CS-1", "/v1/cases/CS-10231%00",
                                  "/v1/customers/" + "A" * 40])
def test_malformed_ids_are_400(send, auth, path):
    assert send("GET", path, headers=auth("support-agent")).status_code == 400


# ---- upstream failure combinations -----------------------------------------------------

def test_every_upstream_down_at_once(send, auth, mock_app):
    for target in ("cases", "entitlements", "usage"):
        set_fault(mock_app, target, "error")
    h = auth("support-agent")
    customer = send("GET", "/v1/customers/ACC-007", headers=h)
    assert customer.status_code == 200 and customer.json()["degraded"] is True        # snapshot + nulls
    assert customer.json()["usage"] is None and customer.json()["cases"] is None
    assert send("GET", "/v1/cases", headers=h).status_code == 503
    assert send("GET", "/v1/cases/CS-10231", headers=h).status_code == 503
    assert send("POST", "/v1/cases/CS-10232/comments", json={"body": "x"}, headers=h | key()).status_code == 503


def test_upstream_returns_garbage_is_502_not_500(send, auth, mock_app, monkeypatch):
    state = mock_app.state.mock
    state.cases["CS-10231"]["Status"] = "flux-capacitor"          # value our translator refuses to guess
    r = send("GET", "/v1/cases/CS-10231", headers=auth("support-agent"))
    assert r.status_code == 502 and r.json()["upstream"] == "cases"


# ---- concurrency -----------------------------------------------------------------------

def test_concurrent_duplicate_comments_create_exactly_one(client, auth, mock_app):
    headers = auth("support-agent") | key()
    results: list[int] = []

    def post() -> None:
        results.append(client.post("/v1/cases/CS-10232/comments", json={"body": "same"}, headers=headers).status_code)

    threads = [threading.Thread(target=post) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(results) <= {201, 409}
    assert len(mock_app.state.mock.cases["CS-10232"]["Comments"]) == 1


# ---- console static serving ------------------------------------------------------------

@pytest.fixture
def console_app(tmp_path, monkeypatch, mock_app):
    """An app serving a tiny stand-in console, so this test doesn't depend on `npm run build`
    having produced frontend/dist (CI's test job never builds the frontend)."""
    console = tmp_path / "console"
    console.mkdir()
    (console / "index.html").write_text("<!doctype html><title>Support Console</title>", encoding="utf-8")
    monkeypatch.setenv("CONSOLE_DIR", str(console))
    app = create_app(make_settings(tmp_path), clock=lambda: ANCHOR,
                     upstream_transport=httpx.ASGITransport(app=mock_app), run_background=False)
    with TestClient(app) as c:
        yield c


def test_console_is_served_with_redirect_and_404_for_unknown_assets(console_app):
    assert console_app.get("/console", follow_redirects=False).status_code in (307, 308)
    page = console_app.get("/console/")
    assert page.status_code == 200 and "Support Console" in page.text
    assert console_app.get("/console/does-not-exist.js").status_code == 404


def test_api_still_works_when_the_console_was_never_built(tmp_path, monkeypatch, mock_app, auth):
    monkeypatch.setenv("CONSOLE_DIR", str(tmp_path / "missing"))
    app = create_app(make_settings(tmp_path), clock=lambda: ANCHOR,
                     upstream_transport=httpx.ASGITransport(app=mock_app), run_background=False)
    with TestClient(app) as c:
        assert c.get("/console/").status_code == 404           # no console mounted
        assert c.get("/readyz").json()["status"] == "ready"     # but the API is fine


def test_case_search_waits_for_one_upstream_deadline_not_two(client, auth, mock_app):
    """Entitlements and cases are queried concurrently, so a double outage costs one timeout budget."""
    import time

    set_fault(mock_app, "entitlements", "timeout")
    set_fault(mock_app, "cases", "timeout")
    started = time.perf_counter()
    r = client.get("/v1/cases?include=account", headers=auth("support-agent"))
    elapsed = time.perf_counter() - started
    assert r.status_code == 504
    # Per-attempt timeout is 0.5 s with 3 attempts (~1.5 s per upstream); sequential calls would take ~3 s.
    assert elapsed < 2.4, f"took {elapsed:.2f}s"
