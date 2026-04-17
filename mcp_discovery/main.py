"""
MCP Discovery — Agent SDK
=========================
Shows how multiple MCP servers are configured in one place.
The SDK connects to each server at startup, calls tools/list on each,
and merges all discovered tools into a single flat list for the agent.

The [Session] line in the output shows every tool the agent can reach,
regardless of which server it came from.

All three servers require no API tokens.

Setup (one-time):
  npm install -g @modelcontextprotocol/server-filesystem
  npm install -g @modelcontextprotocol/server-memory
  pip install mcp-server-fetch
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions


async def main():
    async for message in query(
        prompt=(
            "Do three things: "
            "1) list the files in /tmp, "
            "2) fetch https://example.com and summarise the page in one sentence, "
            "3) store that summary in memory under the key 'example_dot_com'."
        ),
        options=ClaudeAgentOptions(
            model="claude-haiku-4-5-20251001",
            # Each key is the server name — tools are prefixed mcp__<name>__<tool>
            # The SDK spawns each process, calls tools/list, and merges results.
            mcp_servers={
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                },
                "memory": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-memory"],
                },
                "fetch": {
                    "command": "python",
                    "args": ["-m", "mcp_server_fetch"],
                },
            },
        ),
    ):
        print(log_message(message))


asyncio.run(main())
