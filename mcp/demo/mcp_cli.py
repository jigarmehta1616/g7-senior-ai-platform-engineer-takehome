"""Minimal MCP host for demos and transcript recording.

Launches the Support Copilot MCP server over stdio (exactly as Claude Desktop / Cursor
would), then lists the tools or calls one and prints the result. Human approval requests
(MCP elicitation) are answered on the terminal, or with --approve / --decline.

Tool arguments work in any shell (Command Prompt, PowerShell, bash):

    python mcp/demo/mcp_cli.py list
    python mcp/demo/mcp_cli.py call search_cases priority=P1 support_tier=Platinum min_open_hours=48 renewal_within_days=90
    python mcp/demo/mcp_cli.py call get_case_details case_id=CS-10280
    python mcp/demo/mcp_cli.py call search_cases @mcp/demo/examples/sample_question.json
    python mcp/demo/mcp_cli.py call escalate_case case_id=CS-10280 reason=sla_breach_risk --approve

Run it with the project's virtual environment (.venv), where the dependencies are installed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    import anyio
    import mcp.types as t
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    from support_copilot.cli_args import FORMS_HELP, ArgumentError, parse_tool_arguments
except ModuleNotFoundError as missing:  # pragma: no cover - environment problem, not a code path
    sys.exit(
        f"Missing Python package: {missing.name}\n"
        "Run this with the project's virtual environment, for example:\n"
        "  .venv\\Scripts\\python mcp\\demo\\mcp_cli.py list      (Windows)\n"
        "  .venv/bin/python mcp/demo/mcp_cli.py list          (macOS/Linux)\n"
        "If .venv doesn't exist yet:  python -m venv .venv  then  .venv\\Scripts\\pip install -e \".[dev,agent]\""
    )


def server_params(persona: str) -> StdioServerParameters:
    env = {**os.environ, "COPILOT_PERSONA": persona,
           "PLATFORM_API_URL": os.getenv("PLATFORM_API_URL", "http://127.0.0.1:8080")}
    return StdioServerParameters(command=sys.executable, args=["-m", "support_copilot"], env=env)


def make_elicitation_handler(mode: str):
    async def handler(context, params):
        print("\n--- HUMAN APPROVAL REQUESTED (MCP elicitation) ---")
        print(params.message)
        if mode == "approve":
            print("--- auto-answer: APPROVE (--approve) ---\n")
            return t.ElicitResult(action="accept", content={"approve": True})
        if mode == "decline":
            print("--- auto-answer: DECLINE (--decline) ---\n")
            return t.ElicitResult(action="decline")
        answer = input("Approve? [y/N] ").strip().lower()
        return t.ElicitResult(action="accept", content={"approve": answer == "y"})
    return handler


async def run(args: argparse.Namespace) -> None:
    mode = "approve" if args.approve else "decline" if args.decline else "ask"
    async with Client(server_params(args.persona), elicitation_callback=make_elicitation_handler(mode)) as c:
        tools = {tool.name: tool for tool in (await c.list_tools()).tools}
        if args.command == "list":
            for tool in tools.values():
                print(json.dumps({"name": tool.name, "description": tool.description,
                                  "input_schema": tool.input_schema}, indent=2))
            return
        if args.tool not in tools:
            raise ArgumentError(f"Unknown tool '{args.tool}'. Available: {', '.join(tools)}.")
        arguments: dict[str, Any] = parse_tool_arguments(args.arguments, tools[args.tool].input_schema)
        result = await c.call_tool(args.tool, arguments)
        text = result.content[0].text if result.content else ""
        print(f"is_error={bool(result.is_error)}")
        print(text)


def _first_argument_error(exc: BaseException) -> ArgumentError | None:
    """Errors raised inside the MCP client arrive wrapped in exception groups."""
    if isinstance(exc, ArgumentError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            found = _first_argument_error(inner)
            if found:
                return found
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="Call Support Copilot MCP tools from the terminal.",
                                epilog=FORMS_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["list", "call"])
    p.add_argument("tool", nargs="?", help="tool name, e.g. search_cases")
    p.add_argument("arguments", nargs="*", help="key=value pairs, @file.json, or a JSON object")
    p.add_argument("--persona", default="support-lead",
                   help="who the agent acts for: support-lead, support-agent, finance-analyst, csm")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true", help="auto-approve write actions")
    g.add_argument("--decline", action="store_true", help="auto-decline write actions")
    args = p.parse_args()
    if args.command == "call" and not args.tool:
        p.error("call needs a tool name, e.g.: call search_cases priority=P1")
    if args.command == "call":
        try:  # catch syntax problems before starting the server
            parse_tool_arguments(args.arguments)
        except ArgumentError as exc:
            sys.exit(f"error: {exc}")
    try:
        anyio.run(run, args)
    except Exception as exc:
        arg_error = _first_argument_error(exc)
        if arg_error:
            sys.exit(f"error: {arg_error}")
        sys.exit(f"error: the MCP server couldn't complete the call ({type(exc).__name__}). "
                 "Check the message above. Is the API running? Start it with: python scripts/run_local.py")


if __name__ == "__main__":
    main()
