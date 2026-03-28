from anthropic import AsyncAnthropic

from claude_agent_sdk import (
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)

from lib.logger import log
from lib.partitions import Partitions
from lib.templates import load_prompt
from tools.coordinator_tools import CoordinatorState, make_coordinator_tools

model = "claude-haiku-4-5-20251001"
coordinator_prompt = load_prompt("dynamic_coordinator")


async def run_coordinator(job_posting: str, resume: str) -> tuple[list[dict], dict | None]:
    async with AsyncAnthropic() as anthropic_client:
        partitions = await Partitions.generate(anthropic_client, model, job_posting, resume)
        Partitions.validate_overlap(partitions)

        initial_messages = Partitions.build_initial_messages(partitions, job_posting, resume)
        initial_prompt: str = initial_messages[0]["content"]

        state = CoordinatorState(
            job_posting=job_posting,
            resume=resume,
            partition_by_name=Partitions.index_by_agent(partitions),
            anthropic_client=anthropic_client,
            model=model,
        )

        server = create_sdk_mcp_server(
            "coordinator-tools",
            tools=make_coordinator_tools(state),
        )

        options = ClaudeAgentOptions(
            system_prompt=coordinator_prompt,
            model=model,
            max_turns=30,
            mcp_servers={"coordinator": server},
            permission_mode="bypassPermissions",
        )

        async with ClaudeSDKClient(options=options) as sdk_client:
            await sdk_client.query(initial_prompt)
            async for message in sdk_client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            log.coordinator(state._step_counter[0], block.text.strip())

    return state.trace, state.final_verdict
