import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Tool implementations — your actual business logic
# ---------------------------------------------------------------------------

def tool_check_inventory(item: str) -> str:
    inventory = {"widget-A": 12, "widget-B": 0, "gadget-X": 3}
    qty = inventory.get(item, 0)
    return f"{qty} units of '{item}' available" if qty > 0 else f"'{item}' is out of stock"

def tool_place_order(item: str, quantity: int) -> str:
    return f"Order confirmed: {quantity}x '{item}'. Order ID: ORD-{abs(hash(item)) % 10000:04d}"

def tool_send_notification(recipient: str, message: str) -> str:
    return f"Notification sent to '{recipient}': {message}"

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
            "required": ["item"]
        }
    },
    {
        "name": "place_order",
        "description": "Place a purchase order for a given item and quantity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "quantity": {"type": "integer", "description": "Number of units to order"}
            },
            "required": ["item", "quantity"]
        }
    },
    {
        "name": "send_notification",
        "description": "Send a notification message to a recipient (e.g. 'warehouse', 'manager').",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string"},
                "message": {"type": "string"}
            },
            "required": ["recipient", "message"]
        }
    }
]

# ---------------------------------------------------------------------------
# System prompt — shown here for demonstration purposes.
# Claude doesn't strictly need rigid rules like this, but many models do.
# In production this is where you define persona, constraints, and rules.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an inventory management assistant with tools to check
stock levels, place orders, and send notifications.

When handling a request:
1. Always verify inventory availability before ordering.
2. Only place an order if stock is confirmed available.
3. Notify the relevant team after completing actions.

Use your tools step-by-step — the order in which you call them matters."""

model = "claude-haiku-4-5-20251001"

async def create(client, messages):
    return await client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
    )

async def main() -> None:
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:
        user_message = (
            "I need 5 units of widget-A. Check if they're available, "
            "place the order if so, then notify the warehouse."
        )
        print(f"User: {user_message}\n")
        messages = [{"role": "user", "content": user_message}]

        # --- Agentic loop: the MODEL decides what to do next ---
        step = 0
        while True:
            step += 1
            response = await create(client, messages)
            print(f"[Step {step}] stop_reason={response.stop_reason}")

            if response.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    "(no text)"
                )
                print(f"\nAssistant: {final_text}")
                break

            if response.stop_reason == "tool_use":
                # The model chose which tool(s) to call and with what arguments
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"  → Model calls: {block.name}({json.dumps(block.input)})")
                        result = TOOL_HANDLERS[block.name](**block.input)
                        print(f"    Result: {result}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                # Feed results back — model will decide its next move
                messages += [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ]

asyncio.run(main())
