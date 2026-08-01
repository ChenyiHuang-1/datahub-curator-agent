"""Thin MCP client wrapper around mcp-server-datahub.

Connects over stdio to the official DataHub MCP server so every read and
mutation flows through the same interface any other agent would use.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class DataHubMCP:
    """Sync-friendly facade over an MCP stdio session to mcp-server-datahub."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._loop = asyncio.new_event_loop()
        self.tool_names: list[str] = []

    # -- lifecycle -----------------------------------------------------
    def connect(self) -> list[str]:
        return self._loop.run_until_complete(self._connect())

    async def _connect(self) -> list[str]:
        env = {
            **os.environ,
            "TOOLS_IS_MUTATION_ENABLED": "true",
        }
        params = StdioServerParameters(
            command="mcp-server-datahub",
            args=[],
            env=env,
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        tools = await self._session.list_tools()
        self.tool_names = [t.name for t in tools.tools]
        return self.tool_names

    def close(self) -> None:
        if self._stack is not None:
            self._loop.run_until_complete(self._stack.aclose())
            self._stack = None
        self._loop.close()

    # -- calls ---------------------------------------------------------
    def call(self, tool: str, **arguments: Any) -> Any:
        """Call an MCP tool and return parsed JSON (or raw text)."""
        return self._loop.run_until_complete(self._call(tool, arguments))

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        assert self._session is not None, "call connect() first"
        result = await self._session.call_tool(tool, arguments)
        texts: list[str] = []
        for block in result.content:
            if getattr(block, "type", None) == "text":
                texts.append(block.text)
        raw = "\n".join(texts)
        if result.isError:
            raise RuntimeError(f"MCP tool {tool} failed: {raw[:500]}")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
