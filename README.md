# Customer Entitlement & Support Case Platform

_Author: **Jigar Mehta**_

This project is one API that sits in front of three systems: a case system, an entitlement system and
a usage warehouse. All three are fake versions that run on your machine.

Two kinds of users talk to the API:
- normal apps and integration tools, which use it as a REST API
- an AI helper called the "Support Copilot", which uses the same API through an MCP server

There is also a small web page (the "console") so you can click around and try things.

## Where to find each part

| What the brief asked for | Where it is |
|---|---|
| The API contract (Part A) | [`openapi.yaml`](openapi.yaml) |
| The code and the tests (Part B) | [`src/`](src) and [`tests/`](tests) |
| The MCP server and the demo (Part C) | [`mcp/`](mcp) and [`mcp/demo/TRANSCRIPT.md`](mcp/demo/TRANSCRIPT.md) |
| The Postman collection | [`postman/`](postman) |
| The evals | [TESTEVALS.md](TESTEVALS.md) |
| Security and safety rules | [SECURITY.md](SECURITY.md) |
| My choices, assumptions and what I skipped | [DECISIONS.md](DECISIONS.md) |
| How I used AI tools | [AI_USAGE.md](AI_USAGE.md) |

## How to run it

The easiest way is Docker:

```bash
docker compose up --build
```

If you don't want Docker, you need Python 3.11 or newer and Node 20 or newer:

```bash
python -m venv .venv
.venv/Scripts/activate              # on macOS or Linux: source .venv/bin/activate
pip install -e ".[dev,agent]"
python scripts/run_local.py         # or: make run
```

When it is running, open:
- the API docs: http://localhost:8080/docs
- the console: http://localhost:8080/console/
- the fake systems: http://localhost:8081/docs (you can break them on purpose with `POST /_admin/faults`)

## How to test it

```bash
pytest                          # all 182 tests; the run fails if there is even one warning
ruff check src mcp tests scripts && mypy     # code style and type checks
pytest -m evals -v              # only the 15 AI tool scenarios
(cd frontend && npm run check)  # checks and builds the web page
npx newman run postman/support-platform.postman_collection.json -e postman/local.postman_environment.json
```

The Postman run needs the app to be running (locally or in Docker). It calls every endpoint, makes
78 checks, and you can run it again and again on the same data.

## Try it yourself

```bash
# 1. Get a login token. You can be: support-agent, support-lead, finance-analyst, csm or platform-admin
TOKEN=$(curl -s -X POST localhost:8080/dev/oauth/token -d grant_type=urn:dev:grant-type:persona \
  -d persona=support-lead | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Look at a customer. A support lead can't see the yearly revenue (ARR), so it is hidden.
curl -s localhost:8080/v1/customers/ACC-007 -H "Authorization: Bearer $TOKEN"

# 3. Switch off the usage system. The customer page still works and says "degraded": true.
curl -s -X POST localhost:8081/_admin/faults -H "Content-Type: application/json" -d '{"target":"usage","mode":"error"}'
```

To try the AI helper's tools from your terminal:

```bash
python mcp/demo/mcp_cli.py call search_cases priority=P1 support_tier=Platinum min_open_hours=48 renewal_within_days=90
python mcp/demo/mcp_cli.py call escalate_case case_id=CS-10280 reason=sla_breach_risk   # it will ask you to approve
python mcp/demo/agent_demo.py       # Claude answers the example question (needs an ANTHROPIC_API_KEY)
```

Use the Python inside `.venv`. You can pass tool arguments as `key=value` pairs (this works in every
terminal), as a file like `@mcp/demo/examples/sample_question.json`, or as JSON text (bash and
PowerShell only).

In the console, the **Sample question** button answers the example question from the brief. The
**Resilience lab** tab lets you switch the fake systems off and see how the app copes.
