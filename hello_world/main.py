import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions


async def main():
  async for message in query(
    prompt="Find and fix the bug in hello_world.rb",
    options=ClaudeAgentOptions(allowed_tools=["Read", "Edit", "Bash"]),
  ):
    print(log_message(message))


asyncio.run(main())
