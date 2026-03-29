import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

MODEL = "claude-haiku-4-5-20251001"


async def run_step(step_name: str, prompt: str, tools: list[str] = None) -> str:
    """Run a single pipeline step and return its result."""
    print(f"\n{'='*60}")
    print(f"STEP: {step_name}")
    print(f"{'='*60}")

    options = ClaudeAgentOptions(
        model=MODEL,
        allowed_tools=tools or [],
        max_turns=5,
    )

    result = ""
    async for message in query(prompt=prompt, options=options):
        log_message(message)
        if isinstance(message, ResultMessage):
            result = message.result

    return result


async def main():
    """
    Prompt chaining pipeline — fixed 3-step sequence:

    Step 1 (Read)    — Read hello_world.rb and identify any bugs
    Step 2 (Analyze) — Given the bugs found, propose a fix
    Step 3 (Patch)   — Apply the fix to the file
    """

    # Step 1: Read the file and identify bugs
    step1_result = await run_step(
        step_name="1 / 3  —  Identify bugs",
        prompt=(
            "Read the file hello_world.rb and list every bug you find. "
            "Be concise: output only a numbered list of bugs, nothing else."
        ),
        tools=["Read"],
    )

    # Step 2: Propose fixes based on the bug list from step 1
    step2_result = await run_step(
        step_name="2 / 3  —  Propose fixes",
        prompt=(
            f"Here is a list of bugs found in hello_world.rb:\n\n{step1_result}\n\n"
            "For each bug, write the exact corrected line(s) of Ruby code. "
            "Output only the corrected code snippets, one per bug, with a brief label."
        ),
        tools=[],  # pure reasoning — no file access needed
    )

    # Step 3: Apply the fixes to the file
    await run_step(
        step_name="3 / 3  —  Apply fixes",
        prompt=(
            f"Apply these fixes to hello_world.rb:\n\n{step2_result}\n\n"
            "Use the Edit tool to make each change. "
            "After all edits, run the file with Bash to confirm it executes without errors."
        ),
        tools=["Read", "Edit", "Bash"],
    )

    print("\nPipeline complete.")


asyncio.run(main())
