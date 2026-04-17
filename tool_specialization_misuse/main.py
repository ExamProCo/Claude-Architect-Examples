import anyio
from pathlib import Path
from dotenv import load_dotenv

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    ResultMessage,
    TaskStartedMessage,
    TaskProgressMessage,
    TaskNotificationMessage,
)

load_dotenv(Path(__file__).parent.parent / ".env")

model = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Agent definitions — tools are scoped HERE, not at call time
# ---------------------------------------------------------------------------

# MISUSE: writer given WebSearch + WebFetch it doesn't need for writing
MISUSE_WRITER = AgentDefinition(
    description="Writes a short blog post on the given topic.",
    prompt=(
        "You are a creative blog post writer. Write an original, engaging blog post "
        "of about 100 words on the topic given to you. Return just the post text."
    ),
    tools=["WebSearch", "WebFetch"],   # ← excess tools: a writer shouldn't need these
    model="haiku",
)

# CORRECT: writer has no external tools — must write from its own knowledge
CORRECT_WRITER = AgentDefinition(
    description="Writes a short blog post on the given topic.",
    prompt=(
        "You are a creative blog post writer. Write an original, engaging blog post "
        "of about 100 words on the topic given to you. Return just the post text."
    ),
    tools=[],                          # ← no excess tools: pure writing capability only
    model="haiku",
)

# ---------------------------------------------------------------------------
# Coordinator system prompts
# ---------------------------------------------------------------------------

MISUSE_COORDINATOR = """You are a content coordinator.
Delegate the writing task to the 'writer' agent and return its output as your final answer."""

CORRECT_COORDINATOR = """You are a content coordinator.
Delegate the writing task to the 'writer' agent and return its output as your final answer."""

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_demo(label: str, writer: AgentDefinition, coordinator_prompt: str, topic: str) -> None:
    writer_tools = writer.tools or []
    print(f"\n{'=' * 58}")
    print(f"  [{label}]")
    print(f"  Writer agent tools: {writer_tools if writer_tools else '(none)'}")
    print(f"{'=' * 58}")

    async for message in query(
        prompt=f"Write a short blog post about: {topic}",
        options=ClaudeAgentOptions(
            system_prompt=coordinator_prompt,
            model=model,
            allowed_tools=["Agent"],
            agents={"writer": writer},
        ),
    ):
        if isinstance(message, TaskStartedMessage):
            print(f"  [task started]   id={message.task_id}")
        elif isinstance(message, TaskProgressMessage):
            print(f"  [task progress]  id={message.task_id}  usage={message.usage}")
        elif isinstance(message, TaskNotificationMessage):
            print(f"  [task done]      id={message.task_id}")
        elif isinstance(message, ResultMessage):
            print(f"\n  Result:\n{message.result}")


async def main() -> None:
    topic = "sustainable gardening"

    print("=" * 58)
    print("  Tool Specialization Misuse Demo")
    print("=" * 58)
    print(f"\n  Topic: {topic}")
    print(
        "\n  AgentDefinition.tools scopes tools per agent at definition\n"
        "  time — not passed in at call time. Watch how the MISUSE\n"
        "  writer uses WebSearch/WebFetch instead of writing originally.\n"
    )

    # LEFT: misuse — writer defined with web tools it shouldn't have
    await run_demo(
        label="LEFT — MISUSE: writer has WebSearch + WebFetch",
        writer=MISUSE_WRITER,
        coordinator_prompt=MISUSE_COORDINATOR,
        topic=topic,
    )

    # RIGHT: correct — writer defined with no external tools
    await run_demo(
        label="RIGHT — CORRECT: writer has no external tools",
        writer=CORRECT_WRITER,
        coordinator_prompt=CORRECT_COORDINATOR,
        topic=topic,
    )


anyio.run(main)
