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

RESEARCHER = AgentDefinition(
    description="Researches topics and summarizes key facts.",
    prompt="You are a research assistant. When given a topic, list 3 concise bullet-point facts about it. Be brief.",
    tools=["WebSearch"],
)

WRITER = AgentDefinition(
    description="Turns research notes into a short paragraph.",
    prompt="You are a copywriter. Given a set of facts, write a single engaging paragraph (2-3 sentences) suitable for a general audience.",
    tools=[],
)

model = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a coordinator that produces a short article on a topic.

Steps:
1. Use the 'researcher' agent to gather 3 key facts about the topic.
2. Use the 'writer' agent to turn those facts into a short paragraph.
3. Return the final paragraph as your answer."""

async def main() -> None:
    topic = "the James Webb Space Telescope"
    prompt = f"Write a short article about: {topic}"
    print(f"Topic: {topic}\n")
    print("-" * 50)

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            model=model,
            allowed_tools=["Agent"],
            agents={
                "researcher": RESEARCHER,
                "writer": WRITER,
            }
        ),
    ):
        if isinstance(message, TaskStartedMessage):
            print(f"[Task started]  id={message.task_id}")
        elif isinstance(message, TaskProgressMessage):
            print(f"[Task progress] id={message.task_id}  tokens so far: {message.usage}")
        elif isinstance(message, TaskNotificationMessage):
            print(f"[Task done]     id={message.task_id}")
        elif isinstance(message, ResultMessage):
            print(f"\nResult:\n{message.result}")


anyio.run(main)
