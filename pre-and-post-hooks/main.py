import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher


async def pre_tool_hook(input_data, tool_use_id, context):
    tool = input_data.get("tool_name", "unknown")
    print(f"[PRE ] Tool: {tool} | ID: {tool_use_id}")
    return {}


async def post_tool_hook(input_data, tool_use_id, context):
    tool = input_data.get("tool_name", "unknown")
    print(f"[POST] Tool: {tool} | ID: {tool_use_id}")
    return {}


async def main():
    async for message in query(
        prompt="Find and fix the bug in hello_world.rb",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash"],
            hooks={
                "PreToolUse": [HookMatcher(matcher=".*", hooks=[pre_tool_hook])],
                "PostToolUse": [HookMatcher(matcher=".*", hooks=[post_tool_hook])],
            },
        ),
    ):
        print(log_message(message))


asyncio.run(main())