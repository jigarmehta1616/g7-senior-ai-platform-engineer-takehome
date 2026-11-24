---
name: devops-release
description: Run, package and ship the Support Platform - local stack, Docker image and compose, CI workflow, configuration and environment variables, health probes and release checks. Use when changing how the system is built, configured, run or deployed.
---

# DevOps & release playbook

## Run
| Goal | Command |
|---|---|
| Local stack (any OS) | `.venv/Scripts/python scripts/run_local.py` (`python scripts/run_local.py` on Linux/macOS) |
| With make | `make run` |
| Containers | `docker compose up --build` (API :8080, upstreams :8081; Node stage builds the console) |
| Console dev server | `cd frontend && npm run dev` (HMR on :5173, proxies the API) |
| MCP server (stdio) | `COPILOT_PERSONA=support-lead python -m support_copilot` |

## Configuration
- Twelve-factor: all config via env (`Settings.from_env`, `.env.example`).
- `ENV=local` enables the dev IdP + console. Any other `ENV` refuses to boot with local secrets or
  the dev IdP enabled — keep that check when adding settings.
- New setting: add to `Settings`, `from_env`, `.env.example`, and README if user-facing.

## Image
- Multi-stage, non-root (uid 10001), read-only root FS in compose, `no-new-privileges`, data on a volume.
- One image, two commands (API / upstreams). Keep `openapi.yaml` and `frontend/` copied in.

## Probes
- `/healthz` liveness (process up). `/readyz` readiness = our DB reachable; upstream breaker states
  are reported but don't fail readiness (we degrade instead of flapping).

## CI (`.github/workflows/ci.yml`)
lint -> pytest (unit, integration, contract, evals) -> newman against a live stack -> docker build.
A red contract test blocks merge: fix the code or deliberately change the spec.

## Release checklist
- [ ] `rtk test .venv/Scripts/python -m pytest -q` green, `ruff` clean
- [ ] spec version bumped if the contract changed; CHANGELOG/deprecations noted
- [ ] secrets come from the platform secret store, not env files
- [ ] `docker compose up` smoke: `/readyz`, console, one escalation -> webhook verified
