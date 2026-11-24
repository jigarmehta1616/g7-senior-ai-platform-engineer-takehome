---
name: mcp-agent-tools
description: Design, add or change Support Copilot MCP tools (mcp/support_copilot) - tool schemas and descriptions for LLMs, guardrails (prompt injection, PII redaction, size limits), human approval via elicitation, delegated identity, per-agent rate limits and tool-call audit. Use for anything agent-facing.
---

# MCP agent tools playbook

## Tool design rules
- Intent-level tools, not REST mirrors: accept what the model naturally has (`min_open_hours`,
  `renewal_within_days`) and convert to API params server-side.
- Closed sets are `Literal[...]` enums; every int has `ge/le`; every string has `max_length`/pattern.
- Descriptions say *when* to use the tool and give one worked example of arguments.
- Responses: compact JSON (`guardrails.compact`), only fields needed to answer, snake_case,
  plus `withheld`, `degraded_sources`, `notes`, `untrusted_fields` so the model can be honest.
- Return `CallToolResult` with `is_error=True` + a `hint` for recoverable failures (403/404/412/429/503).
- Annotate: `read_only_hint` for reads, `destructive_hint` for escalate.

## Guardrails that must hold (tests/mcp enforce them)
1. Identity: server refuses non-delegated tokens (`identity.py`); it holds no credentials of its own.
2. Writes go through `Resolve(ask_...)` -> `Elicit[Approval]`. The approval parameter is never in the
   input schema. No elicitation capability => fail closed. Include anything whose change should
   force re-approval (e.g. the ETag) in the rendered question — the SDK reuses an answer only
   when the question renders identically.
3. Untrusted text passes `clean_untrusted` (injection patterns withheld, PII masked, truncated).
4. `strip_forbidden` removes ARR/contact keys even if the API returned them.
5. `fit_to_budget` keeps outputs under `MAX_OUTPUT_CHARS`.
6. `ToolRateLimiter` per (user, agent, class); escalations peek before asking the human.
7. Every call writes one `ToolAuditLog` record and sends `X-Correlation-ID` + `X-Agent-Tool`.

## mcp 2.x notes
- `from mcp.server.mcpserver import MCPServer, Context, Resolve, Elicit, ElicitationResult`.
- `server.py` must NOT use `from __future__ import annotations` (closure-local resolvers in
  annotations must evaluate eagerly).
- Tests: `Client(server_instance, elicitation_callback=...)` runs in-process.

## Adding a tool
1. Does the API already support it? If not, `api-contract` + `backend-api` skills first.
2. Implement inside `build_server` using `run_tool(name, class, audit_args, body)`.
3. Add eval scenarios to `tests/mcp/test_copilot_mcp.py` and document them in `TESTEVALS.md`.

## Verify
```
rtk test .venv/Scripts/python -m pytest -m evals -q
.venv/Scripts/python mcp/demo/mcp_cli.py list
```
