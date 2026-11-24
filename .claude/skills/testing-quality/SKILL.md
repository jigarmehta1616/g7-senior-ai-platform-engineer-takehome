---
name: testing-quality
description: Write or fix tests for the Support Platform - unit, integration (in-process API + mock upstreams), contract tests against openapi.yaml, MCP evals and the Postman regression collection. Use when adding features, reproducing bugs, or when a test fails.
---

# Testing playbook

## Pyramid
| Layer | Where | What it proves |
|---|---|---|
| Unit | `tests/unit` | Pure rules: escalation, cursor, idempotency, breaker, signing, auth, translators |
| Integration | `tests/integration` | Real HTTP behaviour against mock upstreams with fault injection |
| Contract | `tests/contract` | Every response matches `openapi.yaml`; routes and spec don't drift |
| Evals | `tests/mcp` | MCP tools end to end: answer quality, guardrails, HITL, audit |
| Regression | `postman/` | Same flows as a black box against a running stack (newman in CI); edit the collection JSON directly |

## Fixtures (tests/conftest.py)
- Everything in-process: mock upstreams via `httpx.ASGITransport`, frozen clock `ANCHOR`
  (2026-11-24T12:00Z), `MOCK_REBASE_TIME` off, temp SQLite per test. No network, no ports.
- `auth("support-lead")` -> headers; `delegated_token(client, persona)` -> agent token.
- `set_fault(mock_app, "usage", "error"|"timeout"|"flaky", fail_next=N)` for resilience tests.
- Background loops don't run in tests; drive them: `client.portal.call(container.relay.publish_pending)`.

## Rules
- Reproduce a bug with a failing test before fixing it; name it after the behaviour.
- Assert on contract-visible behaviour (status, problem `type`, headers), not internals.
- Every new endpoint/status gets a `check(...)` call in `tests/contract/test_contract.py`.
- Never relax an assertion that encodes a guardrail; if a guardrail test is wrong, explain why.
- Keep the suite under ~10s; timeouts in tests use 0.5s budgets.

## Commands
```
rtk test .venv/Scripts/python -m pytest -q
rtk test .venv/Scripts/python -m pytest -m "contract or evals" -q
npx newman run postman/support-platform.postman_collection.json -e postman/local.postman_environment.json
```
