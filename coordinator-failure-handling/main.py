import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# isError helpers
# ---------------------------------------------------------------------------

def make_error(error_type: str, message: str, **extra) -> dict:
    payload = {"type": error_type, "message": message, **extra}
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "is_error": True}

def make_ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_inventory = {"widget-A": 12, "widget-B": 0, "gadget-X": 3}

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
# System prompts — define each subagent's failure strategy
# ---------------------------------------------------------------------------

# LEFT SIDE: subagent immediately propagates every failure
NAIVE_SUBAGENT_SYSTEM = """You are an inventory operations subagent.
You have tools to check inventory, place orders, and send notifications.

When a tool returns is_error: true, STOP IMMEDIATELY and respond with:
{"status": "failed", "error_type": "<type>", "message": "<message>", "failed_tool": "<tool>"}

Do NOT attempt any recovery or alternatives. Propagate every failure immediately."""

# RIGHT SIDE: subagent recovers locally, propagates only what it cannot fix
RESILIENT_SUBAGENT_SYSTEM = """You are an inventory operations subagent with local recovery capabilities.
You have tools to check inventory, place orders, and send notifications.

Recovery rules — attempt these BEFORE reporting failure:

  transient   -> retry the same call up to 2 times
  validation  -> fix the identified field and retry with corrected input
  business    -> try a reasonable alternative; note it but continue other tasks
  permission  -> try an alternate recipient (e.g. if 'executive team' is denied,
                 try 'manager' or 'operations lead'); continue with remaining tasks

Complete ALL tasks before reporting. Respond with:
  {"status": "success", "summary": "<what was accomplished>"}
  or if some tasks failed after recovery:
  {"status": "completed", "summary": "<successes>", "failures": ["<what failed and why>"]}"""

COORDINATOR_SYSTEM = """You are an inventory management coordinator.
You delegate tasks to an operations subagent and report results to the user.

The subagent returns JSON:
  "success"   -> everything worked
  "completed" -> partial success with failures array
  "failed"    -> early stop, nothing completed after the error

Provide a concise, clear summary for the user."""

model = "claude-haiku-4-5-20251001"
MAX_SUBAGENT_STEPS = 12

# ---------------------------------------------------------------------------
# Subagent runner — its own Claude instance with its own tool loop
# ---------------------------------------------------------------------------

async def run_subagent(client, task: str, system_prompt: str, label: str) -> str:
    """
    Run a subagent: a separate Claude call with tool access.
    Returns the subagent's final JSON report string.
    """
    print(f"\n  ┌─ SUBAGENT [{label}] {'─' * (44 - len(label))}")
    print(f"  │  Task: {task[:75]}{'...' if len(task) > 75 else ''}")

    messages = [{"role": "user", "content": task}]

    for step in range(MAX_SUBAGENT_STEPS):
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
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
    return '{"status": "failed", "message": "subagent exceeded max steps"}'


# ---------------------------------------------------------------------------
# Coordinator — orchestrates the subagent and reports to the user
# ---------------------------------------------------------------------------

async def run_coordinator(client, user_message: str, use_resilient: bool) -> None:
    mode = "RESILIENT" if use_resilient else "NAIVE"
    subagent_system = RESILIENT_SUBAGENT_SYSTEM if use_resilient else NAIVE_SUBAGENT_SYSTEM

    print(f"\n{'=' * 58}")
    print(f"  COORDINATOR  [{mode} subagent]")
    print(f"{'=' * 58}")
    print(f"  Delegating task to subagent...")

    # Step 1: subagent handles execution (with or without recovery)
    subagent_report = await run_subagent(client, user_message, subagent_system, mode)

    # Step 2: coordinator interprets the report for the user
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
        print("  Subagent Failure Recovery Demo")
        print("=" * 58)
        print(f"\n  User request:\n  {user_message}")
        print(f"\n  The 'executive team' notification triggers a permission")
        print(f"  error. Watch how each subagent mode handles it.\n")

        # ── LEFT SIDE: naive subagent — stops at first error ───────────────
        print("\n  [LEFT SIDE]  Naive: subagent immediately propagates failures")
        await run_coordinator(client, user_message, use_resilient=False)

        # ── RIGHT SIDE: resilient subagent — recovers locally ──────────────
        print(f"\n\n  [RIGHT SIDE] Resilient: subagent attempts local recovery first")
        await run_coordinator(client, user_message, use_resilient=True)


asyncio.run(main())
