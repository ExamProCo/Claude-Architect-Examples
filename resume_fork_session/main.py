import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions, SystemMessage, ResultMessage


async def main():
  session_id = None

  print("=== Session 1: Initial query ===")
  async for message in query(
    prompt="Find and fix the bug in hello_world.rb",
    options=ClaudeAgentOptions(
      allowed_tools=["Read", "Edit", "Bash"],
      model="claude-haiku-4-5-20251001",
    ),
  ):
    log_output = log_message(message)
    if log_output:
      print(log_output)
    if isinstance(message, SystemMessage) and message.subtype == "init":
      session_id = message.data.get("session_id")
      print(f"[session_id captured: {session_id}]")

  print("\n=== Session 2: Resume — follow-up in same context ===")
  async for message in query(
    prompt="Now add a comment at the top of the file explaining what it does",
    options=ClaudeAgentOptions(
      resume=session_id,
      allowed_tools=["Read", "Edit"],
      model="claude-haiku-4-5-20251001",
    ),
  ):
    log_output = log_message(message)
    if log_output:
      print(log_output)

  print("\n=== Session 3: Fork — branch from session 1 with a different task ===")
  async for message in query(
    prompt="Instead of fixing the bug, explain what the bug is and why it occurs",
    options=ClaudeAgentOptions(
      fork_session=session_id,
      allowed_tools=["Read"],
      model="claude-haiku-4-5-20251001",
    ),
  ):
    log_output = log_message(message)
    if log_output:
      print(log_output)
    if isinstance(message, ResultMessage):
      print(f"\n[Fork result]: {message.result}")


asyncio.run(main())
