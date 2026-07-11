"""Smoke-test the Streamable HTTP MCP endpoint.

The script performs a real MCP initialize handshake and verifies that the
Wildberries review tool is advertised by tools/list.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check_once(url: str) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            tool_names = {tool.name for tool in result.tools}

            expected = "get_wb_reviews"
            if expected not in tool_names:
                raise RuntimeError(
                    f"Expected tool {expected!r} was not advertised. "
                    f"Available tools: {sorted(tool_names)}"
                )

            print(f"MCP handshake OK: {url}")
            print(f"Available tools: {sorted(tool_names)}")


async def main() -> None:
    url = os.getenv("MCP_SMOKE_URL", "http://127.0.0.1:8000/mcp")
    attempts = int(os.getenv("MCP_SMOKE_ATTEMPTS", "30"))
    delay = float(os.getenv("MCP_SMOKE_DELAY", "1"))

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await check_once(url)
            return
        except Exception as exc:  # Server startup can race the first attempts.
            last_error = exc
            print(
                f"MCP smoke attempt {attempt}/{attempts} failed: {exc}",
                file=sys.stderr,
            )
            if attempt < attempts:
                await asyncio.sleep(delay)

    raise RuntimeError(f"MCP smoke test failed after {attempts} attempts") from last_error


if __name__ == "__main__":
    asyncio.run(main())
