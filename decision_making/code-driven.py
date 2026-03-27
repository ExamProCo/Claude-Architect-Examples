import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

model = "claude-haiku-4-5-20251001"

CLASSIFIER_PROMPT = """You are a customer support classifier.
Classify the user message into exactly one of these categories:
- billing
- technical
- general

Respond with only the category name, nothing else."""


# --- Hardcoded decision handlers ---

def handle_billing(message: str):
    print(f"[BILLING] Routing to billing team.")
    print(f"  Action: Pull account record and check payment status.")

def handle_technical(message: str):
    print(f"[TECHNICAL] Routing to tech support.")
    print(f"  Action: Create a support ticket and check system status.")

def handle_general(message: str):
    print(f"[GENERAL] Routing to general support.")
    print(f"  Action: Send FAQ links and escalate if unresolved.")

def handle_unknown(category: str, message: str):
    print(f"[UNKNOWN] Unrecognized category '{category}' — defaulting to general queue.")
    handle_general(message)


# --- Decision tree driven by code ---

def route(category: str, message: str):
    category = category.strip().lower()
    if category == "billing":
        handle_billing(message)
    elif category == "technical":
        handle_technical(message)
    elif category == "general":
        handle_general(message)
    else:
        handle_unknown(category, message)


async def classify(client: AsyncAnthropic, message: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=16,
        system=CLASSIFIER_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text


async def main():
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:
        messages = [
            "I was charged twice this month, can you help?",
            "My app keeps crashing after the latest update.",
            "What are your business hours?",
        ]

        for message in messages:
            print(f"\nUser: {message}")
            category = await classify(client, message)
            print(f"  Claude classified as: '{category}'")
            route(category, message)


asyncio.run(main())
