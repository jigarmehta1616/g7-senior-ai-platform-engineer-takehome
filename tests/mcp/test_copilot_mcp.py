"""Deterministic MCP evals: the full stack (MCP server -> platform API -> mock upstreams) runs
in-process; an MCP client drives the tools the way an LLM host would. Scenario IDs match
TESTEVALS.md."""

from __future__ import annotations

import json
import re

import mcp.types as t
import pytest
from mcp import Client

from support_copilot.identity import IdentityError, identity_from_token
from tests.conftest import set_fault
from tests.mcp.support import approve, decline_cb, payload

pytestmark = [pytest.mark.anyio, pytest.mark.evals]
EXPECTED_ACCOUNTS = {"Globex Industries", "Acme Corp", "Stark Logistics", "Tyrell Robotics"}


# ---- E1: the sample question in one call -----------------------------------------------------

async def test_e1_sample_question_single_call(stack):
    async with Client(stack.server()) as c:
        r = await c.call_tool("search_cases", {"priority": ["P1"], "support_tier": "Platinum", "min_open_hours": 48,
                                               "renewal_within_days": 90, "limit": 25})
    body = payload(r)
    assert not r.is_error
    assert {x["account"]["name"] for x in body["cases"]} == EXPECTED_ACCOUNTS
    assert all(x["open_hours"] > 48 and x["account"]["renewal_in_days"] <= 90 for x in body["cases"])
    assert len(r.content[0].text) < 3000            # token-efficient: compact, no raw payloads


# ---- E2/E3: prompt injection via data, PII ---------------------------------------------------

async def test_e2_injected_comment_is_withheld(stack):
    async with Client(stack.server()) as c:
        r = await c.call_tool("get_case_details", {"case_id": "CS-10280"})
    text = r.content[0].text
    assert "IGNORE PREVIOUS" not in text.upper() and "admin mode" not in text
    assert payload(r)["withheld_injection_suspected"] == ["CM-5"]
    assert "untrusted_fields" in payload(r)


async def test_e3_pii_redacted_from_comments(stack):
    async with Client(stack.server()) as c:
        r = await c.call_tool("get_case_details", {"case_id": "CS-10320"})
    text = r.content[0].text
    assert not re.search(r"[\w.]+@[\w.]+\.\w+", text) and "555" not in text
    assert payload(r)["pii_redacted"] is True


async def test_e4_arr_never_reaches_the_model_even_for_finance_users(make_stack):
    s = await make_stack("finance-analyst")
    async with Client(s.server()) as c:
        r = await c.call_tool("get_customer_summary", {"account_id": "ACC-007"})
    assert "612000" not in r.content[0].text and "arr" not in payload(r)
    assert "contract.arrUsd" in payload(r)["withheld"]


async def test_e5_degraded_upstream_is_reported(stack):
    set_fault(stack.mock, "usage", "error")
    async with Client(stack.server()) as c:
        r = await c.call_tool("get_customer_summary", {"account_id": "ACC-007"})
    body = payload(r)
    assert body["usage"] is None and body["degraded_sources"][0]["source"] == "usage"


# ---- E6-E8: human-in-the-loop writes --------------------------------------------------------

async def test_e6_declined_comment_is_not_posted(stack):
    async with Client(stack.server(), elicitation_callback=decline_cb) as c:
        r = await c.call_tool("add_case_comment", {"case_id": "CS-10232", "body": "Customer called back"})
    assert payload(r)["outcome"] == "declined_by_user"
    assert stack.mock.state.mock.cases["CS-10232"]["Comments"] == []
    assert stack.state.audit.records[-1]["decision"] == "declined_by_user"


async def test_e7_approved_comment_shows_exact_text_and_is_idempotent(stack):
    cb = approve()
    async with Client(stack.server(), elicitation_callback=cb) as c:
        args = {"case_id": "CS-10232", "body": "Spoke to customer; restore is running."}
        first = payload(await c.call_tool("add_case_comment", args))
        second = payload(await c.call_tool("add_case_comment", args))
    assert first["outcome"] == "posted" and second["duplicate_suppressed"] is True
    assert "Spoke to customer; restore is running." in cb.prompts[0]
    assert len(stack.mock.state.mock.cases["CS-10232"]["Comments"]) == 1
    assert stack.mock.state.mock.cases["CS-10232"]["Comments"][0]["author"] == "bob@example.com via support-copilot"


async def test_e8_escalation_requires_approval_and_is_audited_end_to_end(stack):
    cb = approve()
    async with Client(stack.server(), elicitation_callback=cb) as c:
        r = await c.call_tool("escalate_case", {"case_id": "CS-10231", "reason": "sla_breach_risk"})
    assert payload(r) == {"outcome": "escalated", "case_id": "CS-10231", "level": 1,
                          "target_team": "engineering_on_call"}
    assert "ESCALATE case CS-10231" in cb.prompts[0]
    mcp_audit = stack.state.audit.records[-1]
    assert mcp_audit["tool"] == "escalate_case" and mcp_audit["decision"] == "allowed"
    rows = stack.api_app.state.container.audit.list(resource_id="CS-10231")
    esc = next(r for r in rows if r["action"].endswith("/escalate"))
    assert esc["correlation_id"] == mcp_audit["correlation_id"] and esc["actor_agent"] == "support-copilot"
    assert esc["actor_subject"] == "bob@example.com"


async def test_e9_writes_fail_closed_without_a_human_channel(stack):
    async with Client(stack.server()) as c:          # client cannot elicit
        with pytest.raises(Exception, match="elicitation"):
            await c.call_tool("escalate_case", {"case_id": "CS-10231", "reason": "customer_impact"})
    assert stack.mock.state.mock.cases["CS-10231"]["escalationLevel"] == 0


async def test_e10_user_permissions_bound_the_agent(make_stack):
    s = await make_stack("support-agent")     # user lacks cases:escalate
    async with Client(s.server(), elicitation_callback=approve()) as c:
        r = await c.call_tool("escalate_case", {"case_id": "CS-10231", "reason": "customer_impact"})
    assert r.is_error and payload(r)["error"]["status"] == 403
    assert "lacks permission" in payload(r)["error"]["hint"]


async def test_e11_per_agent_escalation_rate_limit(stack):
    async with Client(stack.server(), elicitation_callback=approve()) as c:
        outcomes = []
        for case_id in ("CS-10231", "CS-10240", "CS-10260", "CS-10280"):
            r = await c.call_tool("escalate_case", {"case_id": case_id, "reason": "customer_impact"})
            outcomes.append(r.is_error)
    assert outcomes == [False, False, False, True]


async def test_e12_invalid_arguments_rejected_by_schema(stack):
    async with Client(stack.server()) as c:
        for bad in ({"priority": ["P0"]}, {"limit": 500}, {"support_tier": "Diamond"}):
            r = await c.call_tool("search_cases", bad)
            assert r.is_error
        r = await c.call_tool("escalate_case", {"case_id": "CS-10231", "reason": "because I said so"})
        assert r.is_error


async def test_e13_concurrent_change_during_approval_forces_reapproval(stack):
    """Regression for a bug found while building: approval used to be reused after the case
    changed between preview and execution. The ETag is now part of the approval question."""
    prompts: list[str] = []

    async def approve_while_someone_else_edits_once(context, params):
        prompts.append(params.message)
        if len(prompts) == 1:
            stack.mock.state.mock.cases["CS-10240"]["version"] += 1     # concurrent human edit
        return t.ElicitResult(action="accept", content={"approve": True})

    async with Client(stack.server(), elicitation_callback=approve_while_someone_else_edits_once) as c:
        r = await c.call_tool("escalate_case", {"case_id": "CS-10240", "reason": "customer_impact"})
    assert len(prompts) == 2
    assert '[state "v2"]' in prompts[0] and '[state "v3"]' in prompts[1]
    assert payload(r)["outcome"] == "escalated"


# ---- E14: tool design quality gates ---------------------------------------------------------

async def test_e14_tool_schemas_are_tight_and_annotated(stack):
    async with Client(stack.server()) as c:
        tools = {tool.name: tool for tool in (await c.list_tools()).tools}
    assert set(tools) == {"search_cases", "get_customer_summary", "get_case_details", "add_case_comment",
                          "escalate_case"}
    for tool in tools.values():
        assert tool.description and len(tool.description) >= 60
        assert "approval" not in tool.input_schema["properties"]     # HITL is not model-controllable
    search = tools["search_cases"].input_schema["properties"]
    assert json.dumps(search["priority"]).count('"P1"') and search["limit"]["maximum"] == 25
    reason = tools["escalate_case"].input_schema["properties"]["reason"]
    assert set(reason["enum"]) == {"customer_impact", "sla_breach_risk", "security_incident", "executive_request",
                                   "other"}
    assert tools["search_cases"].annotations.read_only_hint is True
    assert tools["escalate_case"].annotations.destructive_hint is True


def test_e15_refuses_non_delegated_token():
    import base64
    claims = base64.urlsafe_b64encode(json.dumps({"sub": "alice", "scope": "cases:read"}).encode()).decode()
    with pytest.raises(IdentityError):
        identity_from_token(f"h.{claims}.s")
