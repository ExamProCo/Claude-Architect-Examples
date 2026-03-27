import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

def tool_magic_eyeball(question):
  import random
  return random.choice(["Yes", "No", "Ask again later"])

tools = [
  {
    "name":"magic_eyeball",
    "description": "When the user asks a yes or no fortune telling question call this function",
    "input_schema": {
      "type": "object",
      "properties": {
        "question": {"type": "string"}
      },
      "required": ["question"]
    }
  }
]

model = "claude-haiku-4-5-20251001"

async def create(client, messages):
  return await client.messages.create(
      model=model,
      max_tokens=1024,
      tools=tools,
      messages=messages,
  )

async def main() -> None:
  async with AsyncAnthropic(
      api_key=os.environ.get("ANTHROPIC_API_KEY"),
      http_client=DefaultAioHttpClient(),
  ) as client:
    user_message = "Hey Claude, will I be a billionaire living on Mars in 2026?"
    messages = [{"role": "user", "content": user_message}]
    response = await create(client, messages)
    print('original:')
    print(json.dumps(response.model_dump(), indent=2))
    tool_use = next(block for block in response.content if block.type == "tool_use")
    tool_result = tool_magic_eyeball(**tool_use.input)
    messages += [
        {"role": "assistant", "content": response.content},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": tool_result}]},
    ]
    response = await create(client, messages)
    print('follow up:')
    print(json.dumps(response.model_dump(), indent=2))

    #while response.stop_reason == "tool_use":
    #print(tool_use)

asyncio.run(main())