import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# isError helper — wraps any failure into the MCP tool-result shape
# ---------------------------------------------------------------------------

def make_error(error_type: str, message: str, **extra) -> dict:
    """
    Build an MCP-style tool result with is_error=True.

    error_type values and what the agent should do:
      transient   → wait retryAfter seconds, retry the same call
      validation  → fix the identified field, retry with corrected input
      business    → do NOT retry; escalate to human with context
      permission  → do NOT retry; inform the user you lack access
    """
    payload = {"type": error_type, "message": message, **extra}
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "is_error": True,
    }

def make_ok(text: str) -> dict:
    """Successful tool result."""
    return {"content": [{"type": "text", "text": text}]}

# ---------------------------------------------------------------------------
# Tool implementations — each returns a result dict, never raises
# ---------------------------------------------------------------------------

_inventory = {"widget-A": 12, "widget-B": 0, "gadget-X": 3}

def tool_check_inventory(item: str) -> dict:
    qty = _inventory.get(item, -1)
    if qty == -1:
        # Unknown SKU → transient lookup failure (e.g. catalog service unavailable)
        return make_error(
            "transient",
            f"Inventory service could not resolve SKU '{item}'",
            retryable=True,
            retryAfter=3,
        )
    if qty == 0:
        return make_error("business", f"'{item}' is out of stock", retryable=False)
    return make_ok(f"{qty} units of '{item}' available")

def tool_place_order(item: str, quantity: int) -> dict:
    if quantity < 1:
        return make_error(
            "validation",
            "quantity must be ≥ 1",
            retryable=True,
            field="quantity",
            received=quantity,
        )
    if item == "widget-B":
        # Business rule: discontinued item
        return make_error(
            "business",
            f"'{item}' has been discontinued and cannot be ordered",
            retryable=False,
        )
    order_id = f"ORD-{abs(hash(item)) % 10000:04d}"
    return make_ok(f"Order confirmed: {quantity}× '{item}'.  Order ID: {order_id}")

def tool_send_notification(recipient: str, message: str) -> dict:
    if "executive" in recipient.lower():
        return make_error(
            "permission",
            "Direct messaging to the executive channel requires elevated access",
            retryable=False,
            suggestion="Route through your manager or use the escalation portal",
        )
    return make_ok(f"Notification sent to '{recipient}': {message}")

# ---------------------------------------------------------------------------
# Tool registry + schema
# ---------------------------------------------------------------------------

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
            "properties": {
                "item": {"type": "string", "description": "Item SKU or name"}
            },
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
            "properties": {
                "recipient": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["recipient", "message"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt — includes isError handling rules
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an inventory management assistant with tools to check
stock levels, place orders, and send notifications.

When handling a request:
1. Always verify inventory availability before ordering.
2. Only place an order if stock is confirmed available.
3. Notify the relevant team after completing actions.

## Handling tool errors (is_error: true)

When a tool returns is_error: true, read the "type" field and respond accordingly:

  transient   → the service had a temporary failure; you MAY retry the same call
  validation  → a field was invalid; fix the identified field and retry
  business    → a business rule was violated; do NOT retry — explain this to the user
  permission  → you lack access; do NOT retry — inform the user you cannot perform this action

Never silently swallow an error. Always summarise what succeeded and what failed."""

model = "claude-haiku-4-5-20251001"
MAX_ITERATIONS = 10

async def create(client, messages):
    return await client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
    )

# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

async def main() -> None:
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:
        user_message = (
            "I need 5 units of widget-A. "
            "Check availability, place the order if stock is sufficient, "
            "then notify the warehouse AND the executive team."
        )
        print(f"User: {user_message}\n")
        messages = [{"role": "user", "content": user_message}]

        step = 0
        while step < MAX_ITERATIONS:
            step += 1
            response = await create(client, messages)
            print(f"[Step {step}] stop_reason={response.stop_reason}")

            if response.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    "(no text)",
                )
                print(f"\nAssistant: {final_text}")
                break

            if response.stop_reason == "tool_use":
                tool_results = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    result = TOOL_HANDLERS[block.name](**block.input)
                    is_err = result.get("is_error", False)

                    # ── print diagnostics ──────────────────────────────────
                    label = " [ERROR]" if is_err else ""
                    print(f"  → {block.name}({json.dumps(block.input)}){label}")
                    text_out = result["content"][0]["text"]
                    if is_err:
                        payload = json.loads(text_out)
                        print(f"    isError: type={payload['type']}  msg={payload['message']}")
                    else:
                        print(f"    Result: {text_out}")
                    # ──────────────────────────────────────────────────────

                    # Build the tool_result block.
                    # is_error=True signals to Claude that the tool failed;
                    # the harness does NOT retry automatically — Claude decides
                    # what to do next based on the error type in the payload.
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
        else:
            print(f"\n[Max iterations ({MAX_ITERATIONS}) reached]")

asyncio.run(main())
