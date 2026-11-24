"""Fixtures shared by the MCP tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from tests.mcp.support import Stack, build_stack


@pytest.fixture
async def make_stack(tmp_path) -> AsyncIterator[Callable[[str], Awaitable[Stack]]]:
    """Builds stacks for any persona and closes every one of them after the test."""
    created: list[Stack] = []

    async def factory(persona: str = "support-lead") -> Stack:
        s = await build_stack(tmp_path / persona, persona)
        created.append(s)
        return s

    yield factory
    for s in created:
        await s.close()


@pytest.fixture
async def stack(make_stack) -> Stack:
    return await make_stack()
