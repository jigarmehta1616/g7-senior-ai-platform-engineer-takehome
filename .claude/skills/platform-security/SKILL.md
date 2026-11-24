---
name: platform-security
description: Review or change security controls of the Support Platform and Copilot - OAuth scopes, field-level authorization, delegated agent tokens, webhook signing, audit integrity, input limits, secrets, prompt-injection and PII defences. Use for security reviews and any change touching auth, data exposure or governance.
---

# Platform security playbook

Source of truth for controls is `SECURITY.md`; keep it in sync with code.

## Review checklist for any change
- [ ] AuthN: endpoint uses `require_scopes(...)`; no anonymous data access besides `/healthz`, `/readyz`.
- [ ] AuthZ: least-privilege scope; field-level data (ARR, contact) gated in `api/presenters.py`.
- [ ] Agents: still bounded by token exchange (user ∩ agent scopes); `AGENT_CLIENTS` never gains
      `finance:read`/`pii:read` without a written decision.
- [ ] Input: bounded lengths/ranges, patterns on ids, `extra="forbid"` on bodies, 64 KiB body cap.
- [ ] Writes: idempotency or ETag; author/actor derived from the token, never the body.
- [ ] Output: problem+json without stack traces; `Cache-Control: no-store`; no secrets in logs.
- [ ] Events/webhooks: data-minimised payloads, signed (Standard Webhooks), https outside local.
- [ ] Audit: mutation, denial and agent call paths still recorded; chain verification passes.
- [ ] MCP: new text fields pass `clean_untrusted`; writes need elicitation; rate class assigned.
- [ ] Secrets: none committed; local defaults refused outside `ENV=local` (`Settings.validate`).

## Threats to keep testing
- Prompt injection via case/comment text (`CS-10280` fixture) -> must be withheld, never acted on.
- Confused deputy: agent token used to read ARR -> must be redacted.
- Replay: webhook timestamp tolerance, idempotency key reuse with different body (422).
- Lost update: stale `If-Match` (412); approval reuse after concurrent change (re-prompt).
- Cursor tampering / cross-filter reuse (400).

## Verify
```
rtk test .venv/Scripts/python -m pytest tests/unit/test_security.py tests/mcp -q
rtk err .venv/Scripts/python -m ruff check --select S src mcp
```
