"""Shared helpers for the MCP tests: an in-process stack (mock upstreams -> API -> MCP server),
human-approval callbacks, and result decoding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import mcp.types as t

from mock_upstreams.app import create_mock_app
from support_copilot.api_client import PlatformApi
from support_copilot.audit import ToolAuditLog
from support_copilot.identity import identity_from_token
from support_copilot.server import CopilotState, build_server
from support_platform.api.app import create_app
from tests.conftest import ANCHOR, PERSONA_GRANT, TOKEN_EXCHANGE, make_settings


@dataclass
class Stack:
    mock: Any
    api_app: Any
    api_http: httpx.AsyncClient
    state: CopilotState

    def server(self):
        return build_server(self.state)

    async def close(self) -> None:
        await self.api_http.aclose()
        await self.state.api.aclose()
        await self.api_app.state.container.aclose()   # closes upstream clients and the SQLite connection


async def _token(http: httpx.AsyncClient, persona: str, *, delegated: bool = True) -> str:
    user = (await http.post("/dev/oauth/token", data={"grant_type": PERSONA_GRANT, "persona": persona})).json()
    if not delegated:
        return user["access_token"]
    ex = await http.post("/dev/oauth/token", data={"grant_type": TOKEN_EXCHANGE, "subject_token": user["access_token"],
                                                   "actor_client": "support-copilot"})
    return ex.json()["access_token"]


async def build_stack(tmp_path: Path, persona: str = "support-lead") -> Stack:
    mock = create_mock_app(rebase_time=False)
    api_app = create_app(make_settings(tmp_path), clock=lambda: ANCHOR,
                         upstream_transport=httpx.ASGITransport(app=mock), run_background=False)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://api")
    token = await _token(http, persona)
    api = PlatformApi("http://api", token, transport=httpx.ASGITransport(app=api_app))
    state = CopilotState(api=api, identity=identity_from_token(token), audit=ToolAuditLog(None),
                         clock=lambda: ANCHOR)
    return Stack(mock, api_app, http, state)


def approve(answer: bool = True):
    async def cb(context, params):
        cb.prompts.append(params.message)
        return t.ElicitResult(action="accept", content={"approve": answer})
    cb.prompts = []
    return cb


async def decline_cb(context, params):
    return t.ElicitResult(action="decline")


def payload(result: t.CallToolResult) -> dict:
    return json.loads(result.content[0].text)
