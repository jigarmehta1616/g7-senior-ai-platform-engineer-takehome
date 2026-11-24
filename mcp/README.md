# Support Copilot MCP server

_Author: **Jigar Mehta**_

This is the part that lets an AI assistant use the platform. It speaks MCP, the standard way for AI
tools like Claude Desktop to call outside tools.

Three things are important about it:
- It always works on behalf of a real person, never as itself.
- It has no password or secret of its own.
- It asks a person before it changes anything.

## The tools

| Tool | Changes data? | What it does |
|---|---|---|
| `search_cases` | No | Finds cases with filters. It can answer the example question in one call. |
| `get_customer_summary` | No | Shows a customer's tier, renewal date, usage and number of cases. Never shows revenue or contact details. |
| `get_case_details` | No | Shows one case and its latest comments. Hides personal data and anything that looks like instructions aimed at the AI. |
| `add_case_comment` | Yes | Adds one comment. A person sees the exact text and must approve it. |
| `escalate_case` | Yes, high risk | Escalates one case. A person must approve that exact version of the case. |

## How to run it

Start the API first (`python scripts/run_local.py`). Then:

```bash
COPILOT_PERSONA=support-lead python -m support_copilot          # on your machine: it logs in for you
COPILOT_ACCESS_TOKEN=<delegated token> python -m support_copilot  # anywhere else
```

To use it in Claude Desktop or Cursor, add this to the app's MCP settings. The app must support MCP
"elicitation" (approval prompts). If it doesn't, the read tools still work, but changes are refused.

```json
{
  "mcpServers": {
    "support-copilot": {
      "command": "<repo>/.venv/Scripts/python.exe",
      "args": ["-m", "support_copilot"],
      "env": { "COPILOT_PERSONA": "support-lead", "PLATFORM_API_URL": "http://127.0.0.1:8080" }
    }
  }
}
```

## Trying it from the terminal

Use the Python inside `.venv` (on Windows: `.venv\Scripts\python`).

- `mcp_cli.py list` shows every tool the way the AI sees it.
- `mcp_cli.py call <tool> <arguments>` runs one tool. You can give the arguments in three ways:
  - as `key=value` pairs. This works in every terminal, including Command Prompt. Example:
    `call search_cases priority=P1 support_tier=Platinum min_open_hours=48 renewal_within_days=90`.
    For lists, use commas: `priority=P1,P2`.
  - as a file: `call search_cases @mcp/demo/examples/sample_question.json`. There is an example file for each tool.
  - as JSON text: `call get_case_details '{"case_id":"CS-10280"}'`. This works in bash and PowerShell,
    but not in Command Prompt, because Command Prompt removes the quotes.
- The tools that change data stop and ask you first. Add `--approve` or `--decline` to answer
  automatically. Add `--persona support-agent` (or `finance-analyst`, or `csm`) to act as a different person.
- `agent_demo.py` lets Claude answer the example question by itself. It needs an `ANTHROPIC_API_KEY`.
- [`demo/TRANSCRIPT.md`](demo/TRANSCRIPT.md) is a recorded run. It also explains a bug I found and how I fixed it.
