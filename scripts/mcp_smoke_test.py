"""Start the MCP server over stdio, list its tools, and call two of them.  Run: .venv/bin/python scripts/mcp_smoke_test.py"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    # MCP clients start servers with a minimal environment, so pass ours through (it may hold the API key).
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            r = await session.call_tool("find_watch_spots_tool", {"query": "Chicago Bears fans in Boston"})
            print(r.content[0].text[:700])
            r = await session.call_tool("list_fan_clubs", {"city": "Boston, MA"})
            print(json.loads(r.content[0].text)["clubs"][:2])


asyncio.run(main())
