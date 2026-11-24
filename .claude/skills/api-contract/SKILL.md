---
name: api-contract
description: Change the OpenAPI 3.1 contract (openapi.yaml) - new operations, fields, params, error types, webhooks, deprecations or version bumps. Use before any API behaviour change; covers compatibility rules and how contract tests enforce them.
---

# API contract playbook (contract-first)

`openapi.yaml` is served verbatim at `/openapi.yaml` and `/docs`; FastAPI's generated schema is
disabled so there is exactly one contract.

## Compatibility rules for /v1
Allowed without a new major version:
- new endpoints, new optional request params/fields, new response fields, new problem `type`s,
  new enum values **in responses** (clients must ignore unknown fields/values).
Breaking (needs `/v2`, run side by side >= 6 months):
- removing/renaming fields or params, tightening validation, new required inputs, changing
  semantics/status codes, new enum values in **requests** that old servers reject.

## Deprecating something
1. Mark `deprecated: true` in the spec with a sunset date in the description.
2. Emit `Deprecation` (RFC 9745), `Sunset` (RFC 8594) and `Link: rel="deprecation"` headers
   when used (see `_DEPRECATION_HEADERS` in `api/routes/cases.py`).
3. Log usage by `client_id`; chase consumers before the sunset.

## Checklist for every operation
- `operationId`, tag, `security` with the exact scopes; field-level scopes via `x-required-scope`.
- All error responses via `#/components/responses/*` (problem+json). Authenticated ops must declare
  401, 403, 429 (`test_every_operation_declares_problem_errors` enforces this).
- Writes: idempotency (`Idempotency-Key`) or optimistic concurrency (`If-Match` + `ETag`), and the
  412/428/409/422 cases they imply.
- Lists: cursor pagination (`limit` bounded, opaque `cursor`), no total counts.
- Nullable in 3.1 = `type: [x, 'null']` or `oneOf` with `type: 'null'` — not `nullable: true`.
- Quote YAML strings containing `: ` or `, ` inside flow mappings (`{ description: '...' }`).

## Verify
```
.venv/Scripts/python -c "import yaml; from openapi_spec_validator import validate; validate(yaml.safe_load(open('openapi.yaml', encoding='utf-8')))"
rtk test .venv/Scripts/python -m pytest -m contract -q
```
`tests/contract/test_contract.py` checks: spec validity, route<->spec parity, every response class
against its schema, and the webhook payload schema.
