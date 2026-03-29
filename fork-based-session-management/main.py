import asyncio
import copy
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv(Path(__file__).parent.parent / ".env")

model = "claude-haiku-4-5-20251001"


async def build_baseline(client: anthropic.AsyncAnthropic) -> list[dict]:
    """Run the shared conversation up to the fork point and return its history."""
    messages: list[dict] = []

    messages.append({"role": "user", "content": "Analyse the EV market briefly."})

    response = await client.messages.create(
        model=model,
        max_tokens=512,
        messages=messages,
    )
    assistant_text = response.content[0].text
    messages.append({"role": "assistant", "content": assistant_text})

    print(f"[baseline] complete — {len(assistant_text)} chars, {len(messages)} messages")
    return messages


async def run_branch(
    client: anthropic.AsyncAnthropic,
    name: str,
    baseline: list[dict],
    prompt: str,
) -> tuple[str, str]:
    """Fork from the baseline checkpoint and continue independently."""
    # Deep copy so branches never share list references
    messages = copy.deepcopy(baseline)
    messages.append({"role": "user", "content": prompt})

    response = await client.messages.create(
        model=model,
        max_tokens=512,
        messages=messages,
    )
    return name, response.content[0].text


async def main() -> None:
    client = anthropic.AsyncAnthropic()

    # ── Phase 1: shared baseline ──────────────────────────────────────────────
    print("Building shared baseline...")
    print("-" * 60)
    baseline = await build_baseline(client)

    # All branches start from this exact point — shared up to here
    branches = {
        "optimistic":  "What is the most optimistic 5-year EV adoption scenario? Focus on best-case growth.",
        "pessimistic": "What is the most pessimistic 5-year EV adoption scenario? Focus on risks and headwinds.",
        "regulatory":  "How could upcoming government regulations reshape the EV market over the next 5 years?",
    }

    # ── Phase 2: concurrent forked branches ──────────────────────────────────
    print(f"\nForking into {len(branches)} isolated branches concurrently...")
    print("-" * 60)

    tasks = [
        run_branch(client, name, baseline, prompt)
        for name, prompt in branches.items()
    ]
    results = await asyncio.gather(*tasks)

    # ── Output ─────────────────────────────────────────────────────────────────
    print("\nResults")
    print("=" * 60)
    for name, text in results:
        print(f"\n[{name.upper()}]")
        print(text)
        print("-" * 60)


asyncio.run(main())
