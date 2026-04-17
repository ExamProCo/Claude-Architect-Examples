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
# Additional overlapping tools — intentionally redundant to demonstrate
# the "too many tools" problem: the model struggles to pick the right one
# ---------------------------------------------------------------------------

def tool_check_inventory_live(item: str) -> dict:
    """Real-time inventory lookup (hits live warehouse API)."""
    return tool_check_inventory(item)

def tool_check_inventory_cached(item: str) -> dict:
    """Returns cached inventory count (may be up to 15 min stale)."""
    return tool_check_inventory(item)

def tool_check_inventory_warehouse(item: str, warehouse_id: str = "WH-01") -> dict:
    """Check inventory at a specific warehouse location."""
    return tool_check_inventory(item)

def tool_check_stock_levels(sku: str) -> dict:
    """Query current stock levels for a product SKU."""
    return tool_check_inventory(sku)

def tool_place_order_rush(item: str, quantity: int) -> dict:
    """Place an expedited rush order — higher cost, same-day processing."""
    return tool_place_order(item, quantity)

def tool_place_order_bulk(item: str, quantity: int, discount_code: str = "") -> dict:
    """Place a bulk purchase order (10+ units) to qualify for volume pricing."""
    return tool_place_order(item, quantity)

def tool_place_order_scheduled(item: str, quantity: int, ship_date: str = "") -> dict:
    """Place an order with a scheduled future ship date."""
    return tool_place_order(item, quantity)

def tool_reorder_item(item: str, quantity: int) -> dict:
    """Reorder a previously purchased item using saved preferences."""
    return tool_place_order(item, quantity)

def tool_send_notification_email(recipient: str, subject: str, body: str) -> dict:
    """Send a formal email notification with subject and body."""
    return tool_send_notification(recipient, f"{subject}: {body}")

def tool_send_notification_sms(phone: str, message: str) -> dict:
    """Send an SMS text notification to a phone number."""
    return make_ok(f"SMS sent to '{phone}': {message}")

def tool_send_notification_slack(channel: str, message: str) -> dict:
    """Post a message to a Slack channel."""
    return make_ok(f"Slack message posted to '#{channel}': {message}")

def tool_send_notification_urgent(recipient: str, message: str) -> dict:
    """Send a high-priority urgent notification — use only for critical issues."""
    return tool_send_notification(recipient, f"[URGENT] {message}")

def tool_send_alert(recipient: str, alert_type: str, details: str) -> dict:
    """Send a structured operational alert with a type tag."""
    return tool_send_notification(recipient, f"[{alert_type.upper()}] {details}")

def tool_delegate_task(task_description: str, assignee: str) -> dict:
    """Delegate a task to another team member or department."""
    return make_ok(f"Task delegated to '{assignee}': {task_description}")

def tool_delegate_fulfillment(order_id: str, warehouse: str = "WH-01") -> dict:
    """Hand off an order to the fulfillment team for picking and packing."""
    return make_ok(f"Order '{order_id}' sent to fulfillment at {warehouse}")

def tool_delegate_review(item: str, reason: str) -> dict:
    """Escalate an item for manual review by a supervisor."""
    return make_ok(f"'{item}' flagged for review: {reason}")

def tool_delegate_research(query: str) -> dict:
    """Ask the research team to investigate a product or supplier question."""
    return make_ok(f"Research task queued: {query}")

# ---------------------------------------------------------------------------
# Tool registry + schema
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "check_inventory_live": tool_check_inventory_live,
    "check_inventory_cached": tool_check_inventory_cached,
    "check_inventory_warehouse": tool_check_inventory_warehouse,
    "check_stock_levels": tool_check_stock_levels,
    "place_order_rush": tool_place_order_rush,
    "place_order_bulk": tool_place_order_bulk,
    "place_order_scheduled": tool_place_order_scheduled,
    "reorder_item": tool_reorder_item,
    "send_notification_email": tool_send_notification_email,
    "send_notification_sms": tool_send_notification_sms,
    "send_notification_slack": tool_send_notification_slack,
    "send_notification_urgent": tool_send_notification_urgent,
    "send_alert": tool_send_alert,
    "delegate_task": tool_delegate_task,
    "delegate_fulfillment": tool_delegate_fulfillment,
    "delegate_review": tool_delegate_review,
    "delegate_research": tool_delegate_research,
}

tools = [
    {
        "name": "check_inventory_live",
        "description": "Real-time inventory lookup by hitting the live warehouse API — use when freshness is critical.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
        },
    },
    {
        "name": "check_inventory_cached",
        "description": "Returns a cached inventory count (may be up to 15 minutes stale) — faster but possibly outdated.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
        },
    },
    {
        "name": "check_inventory_warehouse",
        "description": "Check inventory at a specific physical warehouse location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "warehouse_id": {"type": "string", "description": "Warehouse code, e.g. WH-01"},
            },
            "required": ["item"],
        },
    },
    {
        "name": "check_stock_levels",
        "description": "Query current stock levels for a product by SKU.",
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    },
    {
        "name": "place_order_rush",
        "description": "Place an expedited rush order — higher cost, same-day processing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "quantity": {"type": "integer"},
            },
            "required": ["item", "quantity"],
        },
    },
    {
        "name": "place_order_bulk",
        "description": "Place a bulk purchase order (10+ units) to qualify for volume pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "quantity": {"type": "integer"},
                "discount_code": {"type": "string"},
            },
            "required": ["item", "quantity"],
        },
    },
    {
        "name": "place_order_scheduled",
        "description": "Place an order with a scheduled future ship date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "quantity": {"type": "integer"},
                "ship_date": {"type": "string", "description": "ISO date, e.g. 2026-05-01"},
            },
            "required": ["item", "quantity"],
        },
    },
    {
        "name": "reorder_item",
        "description": "Reorder a previously purchased item using saved order preferences.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "quantity": {"type": "integer"},
            },
            "required": ["item", "quantity"],
        },
    },
    {
        "name": "send_notification_email",
        "description": "Send a formal email notification with a subject line and body.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["recipient", "subject", "body"],
        },
    },
    {
        "name": "send_notification_sms",
        "description": "Send an SMS text notification to a phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["phone", "message"],
        },
    },
    {
        "name": "send_notification_slack",
        "description": "Post a message to a Slack channel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name without #"},
                "message": {"type": "string"},
            },
            "required": ["channel", "message"],
        },
    },
    {
        "name": "send_notification_urgent",
        "description": "Send a high-priority urgent notification — use only for critical issues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "send_alert",
        "description": "Send a structured operational alert with an alert type tag (e.g. 'stockout', 'delay').",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string"},
                "alert_type": {"type": "string"},
                "details": {"type": "string"},
            },
            "required": ["recipient", "alert_type", "details"],
        },
    },
    {
        "name": "delegate_task",
        "description": "Delegate a general task to another team member or department.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string"},
                "assignee": {"type": "string"},
            },
            "required": ["task_description", "assignee"],
        },
    },
    {
        "name": "delegate_fulfillment",
        "description": "Hand off an order to the fulfillment team for picking and packing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "warehouse": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "delegate_review",
        "description": "Escalate an item or decision for manual review by a supervisor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["item", "reason"],
        },
    },
    {
        "name": "delegate_research",
        "description": "Ask the research team to investigate a product or supplier question.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
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
