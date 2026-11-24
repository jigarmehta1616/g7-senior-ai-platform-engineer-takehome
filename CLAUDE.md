# Support Platform — working agreement for Claude Code

Customer Entitlement & Support Case API (FastAPI) in front of three mocked upstreams, plus
a Support Copilot MCP server and a zero-build console. Contract-first: `openapi.yaml` is
the source of truth.

## Layout
| Path | What |
|---|---|
| `openapi.yaml` | The contract. Change it **first**; contract tests fail on drift. |
| `src/support_platform/` | API: `api/` (HTTP only) → `services/` (use cases) → `domain/` (pure rules) / `upstreams/` (adapters + resilience) / `persistence/` (SQLite) |
| `src/mock_upstreams/` | Case / entitlement / usage stand-ins with fault injection |
| `mcp/support_copilot/` | MCP server: tools, guardrails, identity, audit |
| `frontend/` | React + TypeScript + Tailwind console (Vite), built to `frontend/dist`, served at `/console/` |
| `tests/` | `unit/`, `integration/`, `contract/`, `mcp/` (evals) |
| `postman/` | Postman collection + local environment (regression suite, run with newman) |

## Commands — always run through RTK (https://github.com/rtk-ai/rtk) to keep output small
```
rtk test .venv/Scripts/python -m pytest -q          # full suite (unit+integration+contract+evals)
rtk test .venv/Scripts/python -m pytest -m contract # contract only
rtk err  .venv/Scripts/python -m ruff check src mcp tests scripts
rtk git status / rtk git diff                       # compact VCS output
.venv/Scripts/python scripts/run_local.py            # API :8080 + upstreams :8081 (same as make run)
rtk npm run check --prefix frontend                 # ESLint (0 warnings) + typecheck + build the console
rtk gain                                            # token savings report
```
Use `rtk read <file>` for large files and `rtk grep`/`rtk find` for searches when a dedicated tool isn't available.

## Rules
- Contract first: edit `openapi.yaml`, then code, then tests. `tests/contract` must stay green.
- Every error leaves through `domain/errors.py` constructors → RFC 9457 problem+json. Never raise HTTPException.
- Upstream field names live only in `upstreams/translators.py`.
- New platform-owned tables = new numbered file in `persistence/migrations/` (forward-only).
- Never weaken a guardrail to make a test pass (scopes, HITL elicitation, redaction, rate limits, audit).
- Business data never gets copied into our DB; we store only what we own.

## Skills
Task-specific playbooks live in `.claude/skills/`: `backend-api`, `api-contract`, `database`,
`frontend-console`, `mcp-agent-tools`, `testing-quality`, `platform-security`, `devops-release`.
