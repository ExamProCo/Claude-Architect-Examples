import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Tool result helpers — every error is TYPED, never generic
# ---------------------------------------------------------------------------

def make_error(error_type: str, message: str, **extra) -> dict:
    payload = {"type": error_type, "message": message, **extra}
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "is_error": True}

def make_ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}

# ---------------------------------------------------------------------------
# Domain tools
# ---------------------------------------------------------------------------

_inventory = {"widget-A": 0, "widget-B": 0, "gadget-X": 3}

def tool_check_inventory(item: str) -> dict:
    qty = _inventory.get(item, -1)
    if qty == -1:
        return make_error("transient", f"Inventory service could not resolve SKU '{item}'", retryable=True, retryAfter=3)
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

# ---------------------------------------------------------------------------
# SCOPED tool sets — each subagent only sees its own tool
# ---------------------------------------------------------------------------

INVENTORY_TOOLS = [
    {
        "name": "check_inventory",
        "description": "Check how many units of an item are currently in stock.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "Item SKU or name"}},
            "required": ["item"],
        },
    },
]

ORDER_TOOLS = [
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
]

NOTIFICATION_TOOLS = [
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
# Structured report contract — every subagent returns this shape
# ---------------------------------------------------------------------------

STRUCTURED_REPORT_FORMAT = """
Return ONLY a JSON object (no surrounding prose) with this exact shape:

{
  "status": "success" | "completed" | "failed",
  "subagent": "<your name>",
  "summary": "<one sentence describing what was accomplished>",
  "attempts": [
    {
      "tool": "<tool_name>",
      "input": { ... },
      "approach": "initial" | "retry_<n>" | "alternative_<short_reason>",
      "outcome": "success" | "<error_type>",
      "detail": "<short note from the tool result>"
    }
  ],
  "failures": [
    {
      "task": "<what you tried to do>",
      "error_type": "<type returned by the tool>",
      "approaches_tried": ["<approach1>", "<approach2>"],
      "final_message": "<reason it could not be fixed>"
    }
  ]
}

status rules:
  "success"   = no failures, no recovery needed
  "completed" = some recovery happened OR some sub-tasks failed but others succeeded
  "failed"    = nothing was accomplished

Never use generic error strings. Every entry must reference a typed error
(transient | validation | business | permission) returned by a tool.
"""

# ---------------------------------------------------------------------------
# Subagent system prompts — domain-specific recovery strategies
# ---------------------------------------------------------------------------

INVENTORY_AGENT_SYSTEM = f"""You are the INVENTORY subagent. Your only tool is check_inventory.

Recovery rules:
  transient  -> retry the same call up to 2 times (the SKU lookup may be flaky)
  business   -> the item exists but is unavailable; report as a clean failure
  validation -> fix the input and retry once

Log every attempt — including retries — in the attempts array.
Never invent stock numbers; only report what the tool returned.
{STRUCTURED_REPORT_FORMAT}"""

ORDER_AGENT_SYSTEM = f"""You are the ORDER subagent. Your only tool is place_order.

Recovery rules:
  validation -> read the 'field' and 'received' fields from the error and retry
                with corrected input (e.g. clamp quantity to >= 1)
  transient  -> retry up to 2 times
  business   -> item cannot be ordered (e.g. discontinued); report as a clean failure

Log every attempt. Never invent order IDs.
{STRUCTURED_REPORT_FORMAT}"""

NOTIFICATION_AGENT_SYSTEM = f"""You are the NOTIFICATION subagent. Your only tool is send_notification.

Recovery rules:
  permission -> if a recipient is denied (e.g. 'executive team'), try alternates
                in this order: 'manager', then 'operations lead'.
                Record which alternate succeeded in the attempts array.
  transient  -> retry up to 2 times
  validation -> fix the input and retry once

Send to ALL requested recipients — do not stop at the first failure.
Continue with remaining recipients even if one fails.
{STRUCTURED_REPORT_FORMAT}"""

# ---------------------------------------------------------------------------
# Coordinator — delegates to subagents via tool calls
# ---------------------------------------------------------------------------

COORDINATOR_TOOLS = [
    {
        "name": "delegate_to_inventory_agent",
        "description": "Send a stock-check task to the inventory subagent. Use FIRST for any order request to verify availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Plain-language task, e.g. 'Check stock for widget-A'"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "delegate_to_order_agent",
        "description": "Send an order placement task to the order subagent. Only call after inventory confirms availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Plain-language task, e.g. 'Place order for 5 units of widget-A'"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "delegate_to_notification_agent",
        "description": "Send a notification task (one or many recipients) to the notification subagent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Plain-language task, e.g. 'Notify warehouse and executive team that order ORD-1234 was placed'"},
            },
            "required": ["task"],
        },
    },
]

COORDINATOR_SYSTEM = """You are the COORDINATOR for an inventory operations workflow.

You delegate work to three specialized subagents (each is a tool call):
  - inventory_agent     -> stock checks
  - order_agent         -> order placement
  - notification_agent  -> messaging

Each subagent returns a STRUCTURED JSON REPORT with these fields:
  status, subagent, summary, attempts[], failures[]

Workflow rules:
  1. Plan the workflow from the user request before delegating.
  2. Delegate one phase at a time. Wait for the report before deciding the next step.
  3. If a subagent reports "failed" on a critical prerequisite (e.g. inventory says
     out of stock), STOP — do not proceed to dependent steps.
  4. If a subagent reports "completed" with partial failures, continue but carry
     those failures forward into your final summary.
  5. After all delegations, give the user a concise outcome summary that:
       - names which subagent succeeded / recovered / failed
       - cites the specific error_type when something failed
       - mentions any alternative approach a subagent used to recover

Never invent results not present in subagent reports."""

model = "claude-haiku-4-5-20251001"
MAX_SUBAGENT_STEPS = 8
MAX_COORDINATOR_STEPS = 8

# ---------------------------------------------------------------------------
# Subagent runner — its own Claude instance with its own scoped tool loop
# ---------------------------------------------------------------------------

async def run_subagent(client, *, name: str, task: str, system_prompt: str, tools: list) -> str:
    print(f"\n  ┌─ SUBAGENT [{name}] {'─' * (44 - len(name))}")
    print(f"  │  Task: {task[:75]}{'...' if len(task) > 75 else ''}")

    messages = [{"role": "user", "content": task}]

    for step in range(MAX_SUBAGENT_STEPS):
        response = await client.messages.create(
            model=model,
            max_tokens=1536,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        print(f"  │  [step {step + 1}] stop_reason={response.stop_reason}")

        if response.stop_reason == "end_turn":
            report = next(
                (b.text for b in response.content if hasattr(b, "text")),
                json.dumps({
                    "status": "failed", "subagent": name,
                    "summary": "subagent produced no output",
                    "attempts": [], "failures": [],
                }),
            )
            preview = report.replace("\n", " ")
            print(f"  │  Report: {preview[:180]}{'...' if len(preview) > 180 else ''}")
            print(f"  └{'─' * 52}")
            return report

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                result = TOOL_HANDLERS[block.name](**block.input)
                is_err = result.get("is_error", False)
                tag = " [ERROR]" if is_err else " [OK]"
                print(f"  │    -> {block.name}({json.dumps(block.input)}){tag}")

                if is_err:
                    payload = json.loads(result["content"][0]["text"])
                    print(f"  │       type={payload['type']}  msg={payload['message']}")
                else:
                    print(f"  │       {result['content'][0]['text']}")

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
    return json.dumps({
        "status": "failed", "subagent": name,
        "summary": "subagent exceeded max steps",
        "attempts": [], "failures": [],
    })


SUBAGENT_REGISTRY = {
    "delegate_to_inventory_agent": {
        "name": "inventory",
        "system": INVENTORY_AGENT_SYSTEM,
        "tools": INVENTORY_TOOLS,
    },
    "delegate_to_order_agent": {
        "name": "order",
        "system": ORDER_AGENT_SYSTEM,
        "tools": ORDER_TOOLS,
    },
    "delegate_to_notification_agent": {
        "name": "notification",
        "system": NOTIFICATION_AGENT_SYSTEM,
        "tools": NOTIFICATION_TOOLS,
    },
}

# ---------------------------------------------------------------------------
# Coordinator runner — its own tool loop, tools = subagent delegations
# ---------------------------------------------------------------------------

async def run_coordinator(client, user_message: str) -> None:
    print(f"\n{'=' * 58}")
    print(f"  COORDINATOR")
    print(f"{'=' * 58}")
    print(f"  User request: {user_message}")

    messages = [{"role": "user", "content": user_message}]

    for step in range(MAX_COORDINATOR_STEPS):
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=COORDINATOR_SYSTEM,
            tools=COORDINATOR_TOOLS,
            messages=messages,
        )

        print(f"\n  COORDINATOR [step {step + 1}] stop_reason={response.stop_reason}")

        if response.stop_reason == "end_turn":
            summary = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "(coordinator produced no response)",
            )
            print(f"\n  COORDINATOR -> User:\n  {summary}\n")
            return

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                spec = SUBAGENT_REGISTRY[block.name]
                print(f"  COORDINATOR delegates -> {block.name}")
                report = await run_subagent(
                    client,
                    name=spec["name"],
                    task=block.input["task"],
                    system_prompt=spec["system"],
                    tools=spec["tools"],
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": report,
                })

            messages += [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
            continue

        print(f"  COORDINATOR unexpected stop_reason; ending loop")
        return

    print(f"\n  COORDINATOR [max steps reached]\n")


# ---------------------------------------------------------------------------
# Main
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

        print("=" * 58)
        print("  Coordinator + 3 Subagents Demo")
        print("=" * 58)
        print(f"\n  A coordinator delegates to three specialized subagents")
        print(f"  (inventory / order / notification). Each subagent has:")
        print(f"    - a SCOPED tool set (only its own tool)")
        print(f"    - DOMAIN-SPECIFIC recovery rules")
        print(f"    - a STRUCTURED report contract:")
        print(f"        status, summary, attempts[], failures[]")
        print(f"\n  The 'executive team' notification triggers a permission")
        print(f"  error — watch the notification subagent recover by trying")
        print(f"  an alternative recipient and recording the approach.\n")

        await run_coordinator(client, user_message)


asyncio.run(main())
