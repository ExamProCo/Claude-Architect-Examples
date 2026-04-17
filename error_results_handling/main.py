import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def make_error(error_type: str, message: str, **extra) -> dict:
    payload = {"type": error_type, "message": message, **extra}
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "is_error": True}

def make_ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}

def make_status(status: str, detail: str | None = None) -> dict:
    """Non-error tool result carrying a structured status code.

    status: "valid_empty"    — lookup succeeded; item simply does not exist
    status: "access_failure" — inventory service unreachable (timeout / outage)
    """
    payload: dict = {"status": status}
    if detail:
        payload["detail"] = detail
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_inventory = {"widget-A": 12, "widget-B": 0, "gadget-X": 3}

# Items that simulate a service outage during lookup
_UNREACHABLE_SKUS = {"gadget-Y", "widget-C"}

def tool_check_inventory(item: str) -> dict:
    if item in _UNREACHABLE_SKUS:
        return make_status(
            "access_failure",
            f"Inventory service unreachable while looking up '{item}': connection timed out",
        )
    qty = _inventory.get(item)
    if qty is None:
        # SKU looked up successfully — it just isn't in the catalog
        return make_status("valid_empty")
    if qty == 0:
        return make_error("business", f"'{item}' is out of stock", retryable=False)
    return make_ok(f"{qty} units of '{item}' available")

def tool_place_order(item: str, quantity: int) -> dict:
    if quantity < 1:
        return make_error("validation", "quantity must be >= 1", retryable=True, field="quantity", received=quantity)
    if item == "widget-B":
        return make_error("business", f"'{item}' has been discontinued and cannot be ordered", retryable=False)
    order_id = f"ORD-{abs(hash(item)) % 10000:04d}"
    return make_ok(f"Order confirmed: {quantity}x '{item}'.  Order ID: {order_id}")

def tool_send_notification(recipient: str, message: str) -> dict:
    if "executive" in recipient.lower():
        return make_error(
            "permission",
            "Direct messaging to the executive channel requires elevated access",
            retryable=False,
            suggestion="Route through your manager or use the escalation portal",
        )
    return make_ok(f"Notification sent to '{recipient}': {message}")

TOOL_HANDLERS = {
    "check_inventory": tool_check_inventory,
    "place_order": tool_place_order,
    "send_notification": tool_send_notification,
}

tools = [
    {
        "name": "check_inventory",
        "description": "Check how many units of an item are currently in stock.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "Item SKU or name"}},
            "required": ["item"],
        },
    },
    {
        "name": "place_order",
        "description": "Place a purchase order for a given item and quantity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "quantity": {"type": "integer", "description": "Number of units to order"},
            },
            "required": ["item", "quantity"],
        },
    },
    {
        "name": "send_notification",
        "description": "Send a notification message to a recipient (e.g. 'warehouse', 'manager').",
        "input_schema": {
            "type": "object",
            "properties": {"recipient": {"type": "string"}, "message": {"type": "string"}},
            "required": ["recipient", "message"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

RESILIENT_SUBAGENT_SYSTEM = """You are an inventory operations subagent with local recovery capabilities.

── isError recovery rules ──────────────────────────────────────────────────
  transient   -> retry the same call up to 2 times
  validation  -> fix the identified field and retry with corrected input
  business    -> try a reasonable alternative; note it but continue other tasks
  permission  -> try an alternate recipient; continue with remaining tasks

── check_inventory status codes (NOT isError) ──────────────────────────────
  {"status": "access_failure"}
      The inventory service could not be reached (timeout / outage).
      → Retry the call up to 2 times before giving up.
      → Do NOT treat this as "item not found" — the service never responded.
      → Report the failure clearly if still unresolvable after retries.

  {"status": "valid_empty"}
      The inventory service responded successfully — the SKU simply does not exist.
      → Do NOT retry — retrying will return the same result.
      → Note that the item is not in the catalog and continue with other tasks.

Complete ALL tasks before reporting. Respond with:
  {"status": "success", "summary": "<what was accomplished>"}
  or if some tasks could not be completed:
  {"status": "completed", "summary": "<successes>", "failures": ["<what failed and why>"]}"""

COORDINATOR_SYSTEM = """You are an inventory management coordinator.
You delegate tasks to an operations subagent and report results to the user.

The subagent returns JSON:
  "success"   -> everything worked
  "completed" -> partial success with failures array

Provide a concise, clear summary for the user."""

model = "claude-haiku-4-5-20251001"
MAX_SUBAGENT_STEPS = 12

# ---------------------------------------------------------------------------
# Subagent runner
# ---------------------------------------------------------------------------

async def run_subagent(client, task: str, label: str) -> str:
    print(f"\n  ┌─ SUBAGENT [{label}] {'─' * (44 - len(label))}")
    print(f"  │  Task: {task[:75]}{'...' if len(task) > 75 else ''}")

    messages = [{"role": "user", "content": task}]

    for step in range(MAX_SUBAGENT_STEPS):
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=RESILIENT_SUBAGENT_SYSTEM,
            tools=tools,
            messages=messages,
        )

        print(f"  │  [step {step + 1}] stop_reason={response.stop_reason}")

        if response.stop_reason == "end_turn":
            report = next(
                (b.text for b in response.content if hasattr(b, "text")),
                '{"status": "failed", "message": "subagent produced no output"}',
            )
            print(f"  │  Report: {report}")
            print(f"  └{'─' * 52}")
            return report

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                result = TOOL_HANDLERS[block.name](**block.input)
                is_err = result.get("is_error", False)
                content_text = result["content"][0]["text"]

                try:
                    parsed = json.loads(content_text)
                    status = parsed.get("status", "")
                    tag = f" [{status.upper()}]" if status else (" [ERROR]" if is_err else " [OK]")
                except (json.JSONDecodeError, AttributeError):
                    tag = " [ERROR]" if is_err else " [OK]"

                print(f"  │    -> {block.name}({json.dumps(block.input)}){tag}")
                print(f"  │       {content_text}")

                tool_result: dict = {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result["content"],
                }
                if is_err:
                    tool_result["is_error"] = True
                tool_results.append(tool_result)

            messages += [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

    print(f"  └─ [max steps reached] {'─' * 30}")
    return '{"status": "failed", "message": "subagent exceeded max steps"}'


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

async def run_coordinator(client, user_message: str, label: str) -> None:
    print(f"\n{'=' * 58}")
    print(f"  COORDINATOR  [{label}]")
    print(f"{'=' * 58}")

    subagent_report = await run_subagent(client, user_message, label)

    coord_response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=COORDINATOR_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Original user request: {user_message}\n\n"
                f"Subagent report: {subagent_report}\n\n"
                "Summarize the outcome for the user in 2-3 sentences."
            ),
        }],
    )

    summary = next(
        (b.text for b in coord_response.content if hasattr(b, "text")),
        "(coordinator produced no response)",
    )
    print(f"\n  COORDINATOR -> User:\n  {summary}")


# ---------------------------------------------------------------------------
# Main — two scenarios showing valid_empty vs access_failure
# ---------------------------------------------------------------------------

async def main() -> None:
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:

        print("=" * 58)
        print("  valid_empty vs access_failure Demo")
        print("=" * 58)
        print("""
  check_inventory returns two distinct empty states:

    valid_empty    — service responded; SKU is not in the catalog
                     → do NOT retry; note the gap and continue

    access_failure — service unreachable (timeout / outage)
                     → retry the call; treat as a real failure if unresolvable
""")

        # ── Scenario A: valid_empty ────────────────────────────────────────
        print("\n  [SCENARIO A]  Item that legitimately does not exist in catalog")
        print("  Expected: agent does NOT retry; notes the gap and continues\n")
        await run_coordinator(
            client,
            "Check inventory for 'widget-Z' and order 3 units if available, "
            "then notify the warehouse of the outcome.",
            label="valid_empty",
        )

        # ── Scenario B: access_failure ─────────────────────────────────────
        print("\n\n  [SCENARIO B]  Item whose inventory lookup triggers a service outage")
        print("  Expected: agent retries, then reports the access failure clearly\n")
        await run_coordinator(
            client,
            "Check inventory for 'gadget-Y' and order 5 units if available, "
            "then notify the warehouse of the outcome.",
            label="access_failure",
        )


asyncio.run(main())
