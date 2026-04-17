import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions

SERVER_SCRIPT = str(Path(__file__).parent / "todo_server.py")

PROMPT = """Demonstrate the difference between MCP resources and MCP tools using the todos server.

Follow these steps in order and label each section clearly:

STEP 1 — RESOURCE READ (initial state):
  Read the todos://list resource. This is a passive read with no side effects.

STEP 2 — TOOL USE (create):
  Use tools to create 3 todos: 'Buy groceries', 'Write tests', 'Deploy to prod'.

STEP 3 — TOOL USE (update):
  Mark 'Write tests' as done using the update tool.

STEP 4 — RESOURCE READ (after mutations):
  Read todos://list again. The resource reflects the changes made by the tools.

STEP 5 — TOOL USE (delete):
  Delete the 'Buy groceries' todo using the delete tool.

STEP 6 — RESOURCE READ (final state):
  Read todos://list one last time to confirm the deletion.

Finally, write a short explanation of the key difference:
  - Resources = passive, read-only data access (no side effects)
  - Tools     = active operations that mutate state
"""


async def main():
    async for message in query(
        prompt=PROMPT,
        options=ClaudeAgentOptions(
            model="claude-haiku-4-5-20251001",
            mcp_servers={
                "todos": {
                    "command": "python",
                    "args": [SERVER_SCRIPT],
                }
            },
            allowed_tools=["mcp__todos__*"],
        ),
    ):
        print(log_message(message))


asyncio.run(main())
