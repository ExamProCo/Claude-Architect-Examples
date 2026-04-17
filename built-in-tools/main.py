import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions

PROJECT_DIR = os.path.join(os.path.dirname(__file__), 'sample_project')

PROMPT = f"""
You are demonstrating all Claude Agent SDK built-in tools on the project at: {PROJECT_DIR}

Please complete each step in order:

1. **Glob** — Find all Python files in the sample_project directory.

2. **Read** — Read the contents of calculator.py.

3. **Grep** — Search for any function definitions (lines starting with 'def') across all files.

4. **Bash** — Run `python3 -c "import sys; sys.path.insert(0, '{PROJECT_DIR}'); from calculator import divide; print(divide(10, 2))"` to test the divide function.

5. **Edit** — Fix the divide function in calculator.py to raise a ValueError when b is 0.

6. **Agent** — Spawn a sub-agent with only the Read tool allowed. Ask it to read utils.py and summarize what it does.

After completing all steps, print a short summary of what each tool did.
"""


async def main():
    print("=== Built-in Tools Demo ===\n")
    async for message in query(
        prompt=PROMPT,
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep", "Agent"],
            model="claude-haiku-4-5-20251001",
        ),
    ):
        print(log_message(message))


asyncio.run(main())
