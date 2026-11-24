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

---

## Step 1: Install what you need

You have two choices. Pick **one**.

**Choice A: Docker (easiest).** You only need:
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), started and running
- Git

**Choice B: Run it directly on your machine.** You need:
- Python 3.11 or newer (`python --version` to check)
- Node.js 20 or newer (`node --version` to check). Only needed for the web console.
- Git

## Step 2: Get the code

```bash
git clone <repo-url>
cd <repo-folder>
```

Use the GitHub link for this repository, then go into the folder it creates. All the commands
below are run from that folder.

---

## Step 3A: Start it with Docker

1. Make sure Docker Desktop is open and running.
2. Build and start everything:

   ```bash
   docker compose up --build
   ```

3. The first build takes a few minutes. It is ready when http://localhost:8080/readyz shows
   `"status":"ready"` in your browser.
4. Jump to **Step 4**.

To stop it later, press `Ctrl+C`, then run `docker compose down`.

## Step 3B: Start it without Docker

1. Create a virtual environment (a private Python folder for this project):

   ```bash
   python -m venv .venv
   ```

2. Turn it on.

   Windows (PowerShell):
   ```powershell
   .venv\Scripts\Activate.ps1
   ```
   macOS or Linux:
   ```bash
   source .venv/bin/activate
   ```

   You should now see `(.venv)` at the start of your terminal line.

3. Install the project and its tools:

   ```bash
   pip install -e ".[dev,agent]"
   ```

4. Start the app:

   ```bash
   python scripts/run_local.py
   ```

   The first time, this also builds the web console (it runs `npm install` and `npm run build` for
   you). After that it starts two things:
   - the API on port **8080**
   - the fake systems on port **8081**

5. Leave this terminal open. Press `Ctrl+C` when you want to stop.

> If PowerShell says running scripts is disabled when you activate the venv, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again. Or skip activating and
> use `.venv\Scripts\python` in place of `python` in every command.

---

## Step 4: Check that it works

Open these in your browser:

| What | Link |
|---|---|
| Health check (should say `ready`) | http://localhost:8080/readyz |
| The web console | http://localhost:8080/console/ |
| The API docs (try every endpoint) | http://localhost:8080/docs |
| The fake systems' docs | http://localhost:8081/docs |

In the console:
1. Choose a person at the top right ("Signed in as"). **Bob (Support Lead)** can do everything.
2. Click **Sample question**. You should see 4 customers: Globex, Acme, Stark and Tyrell.
3. Click a case to open it. You can add a comment or escalate it.
4. Open **Customer 360** and click **Load** to see one customer.
5. Open **Resilience lab**, set `usage` to `error`, then load the customer again. The page still
   works and shows a "Partial data" message. Set it back to `ok` afterwards.

## Step 5: Try the API from the terminal (optional)

These commands use `curl`. They work in bash, Git Bash, and macOS/Linux terminals.

1. Get a login token. You can be `support-agent`, `support-lead`, `finance-analyst`, `csm` or `platform-admin`:

   ```bash
   TOKEN=$(curl -s -X POST localhost:8080/dev/oauth/token -d grant_type=urn:dev:grant-type:persona \
     -d persona=support-lead | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
   ```

2. Look at a customer. A support lead can't see yearly revenue (ARR), so it is hidden:

   ```bash
   curl -s localhost:8080/v1/customers/ACC-007 -H "Authorization: Bearer $TOKEN"
   ```

3. Switch off the usage system. The same request still works, and now says `"degraded": true`:

   ```bash
   curl -s -X POST localhost:8081/_admin/faults -H "Content-Type: application/json" -d '{"target":"usage","mode":"error"}'
   ```

## Step 6: Try the AI helper (MCP)

The app must be running (Step 3). Use the Python inside `.venv`. On Windows that is
`.venv\Scripts\python`. On macOS or Linux it is `.venv/bin/python`. If your venv is activated,
plain `python` works too.

1. See the tools the AI can use:

   ```bash
   python mcp/demo/mcp_cli.py list
   ```

2. Ask the example question from the brief:

   ```bash
   python mcp/demo/mcp_cli.py call search_cases priority=P1 support_tier=Platinum min_open_hours=48 renewal_within_days=90
   ```

3. Look at a case that has a hidden trick in its comments. The trick is held back from the AI:

   ```bash
   python mcp/demo/mcp_cli.py call get_case_details case_id=CS-10280
   ```

4. Escalate a case. It stops and asks you to approve. Type `y` and press Enter:

   ```bash
   python mcp/demo/mcp_cli.py call escalate_case case_id=CS-10280 reason=sla_breach_risk
   ```

Good to know:
- You can give tool arguments as `key=value` pairs (works in every terminal), as a file like
  `@mcp/demo/examples/sample_question.json`, or as JSON text (bash and PowerShell only).
- Add `--persona support-agent` to act as someone else. A support agent is not allowed to escalate.
- To let Claude answer by itself, set `ANTHROPIC_API_KEY` and run `python mcp/demo/agent_demo.py`.
- To use it inside Claude Desktop or Cursor, see [`mcp/README.md`](mcp/README.md).

## Step 7: Run the tests

You need the Choice B setup for this (Step 3B, items 1 to 3). The app does **not** need to be running
for these.

1. Run all 182 tests. The run fails if there is even one warning:

   ```bash
   pytest
   ```

2. Check code style and types:

   ```bash
   ruff check src mcp tests scripts
   mypy
   ```

3. Check and build the web console:

   ```bash
   cd frontend
   npm install
   npm run check
   cd ..
   ```

4. Run only the 15 AI tool scenarios, with names shown:

   ```bash
   pytest -m evals -v
   ```

## Step 8: Run the Postman tests

The app **must** be running for this (Step 3A or 3B).

1. Run the collection with newman (Postman's command-line runner). `npx` downloads it the first time
   (this needs Node.js):

   ```bash
   npx --yes newman run postman/support-platform.postman_collection.json -e postman/local.postman_environment.json
   ```

2. You should see 47 requests and 78 passing checks. You can run it again as often as you like.

You can also open the same two files in the Postman app with **Import**.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| `No module named 'mcp'` or `'support_platform'` | You are using the wrong Python. Activate `.venv` (Step 3B, item 2), or run `.venv\Scripts\python` on Windows. |
| `Expecting value: line 1 column 1` when calling a tool | You are in Command Prompt, which breaks JSON quotes. Use `key=value` arguments instead. |
| `can't reach the platform API` | The app isn't running. Start it (Step 3), then try again. |
| Port 8080 or 8081 is already in use | Another copy is still running. Stop it with `Ctrl+C` or `docker compose down`, then start again. |
| `failed to connect to the docker API` | Docker Desktop isn't running. Open it, wait until it says it is running, then try again. |
| The console page is empty or says 404 | Node.js wasn't found, so the console wasn't built. Install Node 20+, then run `cd frontend && npm install && npm run build`. |

## Useful shortcuts

If you have `make` (macOS, Linux, or Windows with Git Bash/WSL), these do the same as the steps above:

| Command | Does |
|---|---|
| `make install` | Step 3B, item 3 |
| `make run` | Step 3B, item 4 |
| `make test` | Step 7, item 1 |
| `make lint` | Step 7, item 2 |
| `make console` | Installs and builds the web console |
| `make newman` | Step 8 |
| `make docker` | Step 3A |
