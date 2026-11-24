---
name: backend-api
description: Add or change an endpoint, service, or upstream integration in the Support Platform API (FastAPI, src/support_platform). Use for new routes, query params, business rules, resilience behaviour, error handling, or logging changes.
---

# Backend API playbook

## Layering (dependencies point inward)
```
api/routes  ->  services  ->  domain (pure)        upstreams (adapters)   persistence
 HTTP only      use cases     rules, models,       http.py + resilience   SQLite + migrations
                              errors, cursor       translators (ACL)
```
- Routes parse/validate input, call one service method, return a presenter's dict. No business logic.
- Services orchestrate upstreams + persistence; raise `domain.errors` constructors only.
- `domain/` has no I/O and is unit-tested exhaustively (see `domain/escalation.py`).
- Upstream payload shapes appear **only** in `upstreams/translators.py`.
- Wiring happens once in `container.py`; tests swap transport + clock, nothing else.

## Adding an endpoint
1. Load the `api-contract` skill and change `openapi.yaml` first.
2. Route in `api/routes/<area>.py` with `Depends(require_scopes(...))`. Path/query constraints
   (`Path(pattern=...)`, `Query(ge=, le=)`) must mirror the spec.
3. Service method + presenter. Field-level authorization goes in `api/presenters.py` only
   (omit the field, append to `redactedFields`).
4. Mutations: set `request.state.audit_details` (no free text beyond what governance needs).
5. Tests: unit for rules, integration for behaviour, contract assertions in `tests/contract`.

## Errors
- Use `errors.validation_error / not_found / insufficient_scope / business_rule_violation(code=...) /
  invalid_state_transition / upstream_unavailable ...`. Business codes are UPPER_SNAKE and documented in the spec.
- Unhandled exceptions become a generic 500 problem with the correlation ID — never leak internals.

## Upstream calls
- `UpstreamHttp.request(..., retry=...)`: GETs and idempotent writes (`Idempotency-Key` forwarded) may retry;
  non-idempotent writes pass `retry=False`.
- Per-attempt timeout is enforced with `asyncio.wait_for` (works with in-process transports too);
  `upstream_deadline_s` bounds the whole retry sequence.
- 404/409/412/422 from an upstream don't count as breaker failures.
- Aggregations use `asyncio.gather(..., return_exceptions=True)` and degrade per source
  (`degraded`, `dataSources[]`). Core data missing => 503; enrichment missing => null section.

## Observability
- `correlation_id_var` is set per request by `PlatformMiddleware` and forwarded upstream/to webhooks.
- Log with `extra={...}` fields (JSON formatter); never log tokens, comment bodies, ARR or emails.

## Verify
```
rtk test .venv/Scripts/python -m pytest tests/unit tests/integration -q
rtk test .venv/Scripts/python -m pytest -m contract -q
rtk err .venv/Scripts/python -m ruff check src
```
