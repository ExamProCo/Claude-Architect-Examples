import anyio
from pathlib import Path
from dotenv import load_dotenv

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)

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
# MCP tool definitions
# ---------------------------------------------------------------------------

@tool("check_inventory",
      "Check how many units of an item are currently in stock.",
      {"item": str})
async def mcp_check_inventory(args: dict) -> dict:
    result = tool_check_inventory(args["item"])
    return {"content": [{"type": "text", "text": result}]}

@tool("place_order",
      "Place a purchase order for a given item and quantity.",
      {"item": str, "quantity": int})
async def mcp_place_order(args: dict) -> dict:
    result = tool_place_order(args["item"], args["quantity"])
    return {"content": [{"type": "text", "text": result}]}

@tool("send_notification",
      "Send a notification message to a recipient (e.g. 'warehouse', 'manager').",
      {"recipient": str, "message": str})
async def mcp_send_notification(args: dict) -> dict:
    result = tool_send_notification(args["recipient"], args["message"])
    return {"content": [{"type": "text", "text": result}]}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an inventory management assistant with tools to check
stock levels, place orders, and send notifications.

When handling a request:
1. Always verify inventory availability before ordering.
2. Only place an order if stock is confirmed available.
3. Notify the relevant team after completing actions.

Use your tools step-by-step — the order in which you call them matters."""

model = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    user_message = (
        "I need 5 units of widget-A. Check if they're available, "
        "place the order if so, then notify the warehouse."
    )
    print(f"User: {user_message}\n")

    server = create_sdk_mcp_server(
        "inventory-tools",
        tools=[mcp_check_inventory, mcp_place_order, mcp_send_notification],
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        mcp_servers={"inventory": server},
        permission_mode="bypassPermissions",
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_message)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        print(f"\nAssistant: {block.text.strip()}")


anyio.run(main)
