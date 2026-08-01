"""Thin MCP client wrapper around mcp-server-datahub.

Connects over stdio to the official DataHub MCP server so every read and
mutation flows through the same interface any other agent would use.

Implementation note: anyio cancel scopes require the MCP session to be
entered/exited and used from the SAME asyncio task, so we run one long-lived
worker task on a dedicated thread and feed it calls through a queue.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class DataHubMCP:
    """Sync facade over an MCP stdio session (single worker task, thread-safe)."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._requests: asyncio.Queue | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self.tool_names: list[str] = []

    # -- lifecycle -----------------------------------------------------
    def connect(self) -> list[str]:
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=120)
        if self._startup_error is not None:
            raise RuntimeError(f"MCP connect failed: {self._startup_error}")
        if not self.tool_names:
            raise RuntimeError("MCP connect timed out")
        return self.tool_names

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._worker())
        finally:
            self._loop.close()

    async def _worker(self) -> None:
        self._requests = asyncio.Queue()
        env = {**os.environ, "TOOLS_IS_MUTATION_ENABLED": "true"}
        params = StdioServerParameters(command="mcp-server-datahub", args=[], env=env)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.tool_names = [t.name for t in tools.tools]
                    self._ready.set()
                    while True:
                        job = await self._requests.get()
                        if job is None:
                            break
                        tool, arguments, fut = job
                        try:
                            result = await session.call_tool(tool, arguments)
                            fut.get_loop().call_soon_threadsafe(fut.set_result, result)
                        except BaseException as e:  # noqa: BLE001
                            fut.get_loop().call_soon_threadsafe(fut.set_exception, e)
        except BaseException as e:  # noqa: BLE001
            self._startup_error = e
            self._ready.set()

    def close(self) -> None:
        if self._loop is not None and self._requests is not None:
            asyncio.run_coroutine_threadsafe(self._requests.put(None), self._loop).result(timeout=10)
        if self._thread is not None:
            self._thread.join(timeout=15)

    # -- calls ---------------------------------------------------------
    def call(self, tool: str, **arguments: Any) -> Any:
        """Call an MCP tool and return parsed JSON (or raw text)."""
        assert self._loop is not None and self._requests is not None, "call connect() first"
        caller_loop = asyncio.new_event_loop()
        try:
            fut = caller_loop.create_future()
            asyncio.run_coroutine_threadsafe(self._requests.put((tool, arguments, fut)), self._loop)
            result = caller_loop.run_until_complete(asyncio.wait_for(fut, timeout=180))
        finally:
            caller_loop.close()

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
