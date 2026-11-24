"""Run the Support Copilot MCP server over stdio.

Environment:
  PLATFORM_API_URL        default http://127.0.0.1:8080
  COPILOT_ACCESS_TOKEN    a *delegated* token (sub=user, act.sub=support-copilot), or
  COPILOT_PERSONA         local only: mint a persona token from the dev IdP and exchange it
  COPILOT_AUDIT_LOG       default var/mcp-audit.jsonl
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

from support_copilot.api_client import PlatformApi
from support_copilot.audit import ToolAuditLog
from support_copilot.identity import IdentityError, identity_from_token
from support_copilot.server import CopilotState, build_server

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"  # noqa: S105


async def obtain_delegated_token_locally(api_url: str, persona: str) -> str:
    """Local convenience only: user login (persona) + RFC 8693 exchange against the dev IdP."""
    async with httpx.AsyncClient(base_url=api_url, timeout=10) as client:
        user = await client.post("/dev/oauth/token", data={"grant_type": "urn:dev:grant-type:persona",
                                                           "persona": persona})
        user.raise_for_status()
        exchanged = await client.post("/dev/oauth/token", data={
            "grant_type": TOKEN_EXCHANGE, "subject_token": user.json()["access_token"],
            "actor_client": "support-copilot"})
        exchanged.raise_for_status()
        return exchanged.json()["access_token"]


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)   # stdout is the MCP channel
    api_url = os.getenv("PLATFORM_API_URL", "http://127.0.0.1:8080")
    token = os.getenv("COPILOT_ACCESS_TOKEN")
    if not token and os.getenv("COPILOT_PERSONA"):
        try:
            token = asyncio.run(obtain_delegated_token_locally(api_url, os.environ["COPILOT_PERSONA"]))
        except httpx.ConnectError:
            sys.exit(f"Support Copilot: can't reach the platform API at {api_url}. "
                     "Start it first: python scripts/run_local.py (or docker compose up).")
        except httpx.HTTPStatusError as exc:
            sys.exit(f"Support Copilot: sign-in for persona '{os.environ['COPILOT_PERSONA']}' failed "
                     f"(HTTP {exc.response.status_code}). Valid personas: support-lead, support-agent, "
                     "finance-analyst, csm, platform-admin.")
    if not token:
        sys.exit("Set COPILOT_ACCESS_TOKEN (delegated token) or, locally, COPILOT_PERSONA=support-lead")
    try:
        identity = identity_from_token(token)
    except IdentityError as exc:
        sys.exit(str(exc))
    state = CopilotState(api=PlatformApi(api_url, token), identity=identity,
                         audit=ToolAuditLog(os.getenv("COPILOT_AUDIT_LOG", "var/mcp-audit.jsonl")))
    build_server(state).run("stdio")


if __name__ == "__main__":
    main()
