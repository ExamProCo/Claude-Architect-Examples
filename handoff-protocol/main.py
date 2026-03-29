import os
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-haiku-4-5-20251001"

# --- Tool definitions ---

TOOLS = [
    {
        "name": "lookup_order",
        "description": "Look up order details by order ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID to look up"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "attempt_refund",
        "description": "Attempt to process a refund for an order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number", "description": "Refund amount in USD"}
            },
            "required": ["order_id", "amount"]
        }
    },
    {
        "name": "clear_fraud_flag",
        "description": "Attempt to clear a fraud flag on an order. Requires elevated permissions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate this case to a human agent when you cannot resolve it yourself. "
            "Call this when blocked by insufficient permissions or policy limits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why escalation is needed"
                }
            },
            "required": ["reason"]
        }
    }
]

# --- Simulated backend ---

def lookup_order(order_id: str) -> dict:
    if order_id == "ORD-99812":
        return {
            "order_id": "ORD-99812",
            "customer_id": "cust_8821",
            "customer_name": "Sarah Chen",
            "customer_tier": "enterprise",
            "amount": 142.00,
            "status": "flagged",
            "fraud_flag": True,
            "duplicate_charge": True,
            "charge_date": "March 12"
        }
    return {"error": f"Order {order_id} not found"}


def attempt_refund(order_id: str, amount: float) -> dict:
    order = lookup_order(order_id)
    if order.get("fraud_flag"):
        return {
            "success": False,
            "reason": "Order flagged for fraud review — refund blocked until flag is cleared"
        }
    if amount > 100:
        return {
            "success": False,
            "reason": "Refunds over $100 require manual approval"
        }
    return {"success": True, "refund_id": "REF-00123"}


def clear_fraud_flag(order_id: str) -> dict:
    return {
        "success": False,
        "reason": "Insufficient permissions — fraud flag removal requires a senior agent"
    }


def run_tool(name: str, inputs: dict) -> str:
    if name == "lookup_order":
        result = lookup_order(**inputs)
    elif name == "attempt_refund":
        result = attempt_refund(**inputs)
    elif name == "clear_fraud_flag":
        result = clear_fraud_flag(**inputs)
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result)


# --- Handoff builder ---

async def build_handoff(
    client: AsyncAnthropic,
    reason: str,
    conversation_history: list,
    tool_results: list
) -> dict:
    synthesis_prompt = f"""You are summarizing a support case for a human agent who will take over.

Based on the conversation and tool results below, produce a JSON handoff package with exactly these fields:
{{
  "customer": {{"id": "...", "name": "...", "tier": "..."}},
  "originalRequest": "...",
  "rootCause": {{"description": "...", "confidence": "high|medium|low"}},
  "attemptedResolutions": [
    {{"action": "...", "outcome": "failed|succeeded", "reason": "..."}}
  ],
  "recommendedActions": ["..."],
  "blockers": ["..."],
  "escalationReason": "..."
}}

Escalation reason from agent: {reason}

Tool results collected:
{json.dumps(tool_results, indent=2)}

Reply with ONLY the JSON object, no other text.
"""

    resp = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system="You are a support operations assistant. Output only valid JSON.",
        messages=conversation_history + [{"role": "user", "content": synthesis_prompt}]
    )
    raw = resp.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def escalate(handoff: dict) -> str:
    """Simulate routing the handoff to a human escalation queue."""
    ticket_id = "TKT-" + handoff["customer"]["id"].replace("cust_", "")
    print("\n" + "=" * 60)
    print("ESCALATION TICKET CREATED")
    print("=" * 60)
    print(f"Ticket ID : {ticket_id}")
    print(f"Customer  : {handoff['customer']['name']} ({handoff['customer']['tier']})")
    print(f"Request   : {handoff['originalRequest']}")
    print(f"\nRoot Cause: {handoff['rootCause']['description']}")
    print(f"Confidence: {handoff['rootCause']['confidence']}")
    print(f"\nAttempted Resolutions:")
    for r in handoff["attemptedResolutions"]:
        print(f"  - {r['action']}: {r['outcome']} — {r['reason']}")
    print(f"\nRecommended Actions:")
    for a in handoff["recommendedActions"]:
        print(f"  - {a}")
    print(f"\nBlockers:")
    for b in handoff["blockers"]:
        print(f"  - {b}")
    print(f"\nEscalation Reason: {handoff['escalationReason']}")
    print("=" * 60)
    return ticket_id


# --- Agentic loop ---

async def run_agent(client: AsyncAnthropic, user_request: str):
    print(f"\nCustomer request: {user_request}\n")

    messages = [{"role": "user", "content": user_request}]
    tool_results_log = []

    while True:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOLS,
            messages=messages
        )

        # Collect any text the agent outputs
        for block in response.content:
            if hasattr(block, "text") and block.text:
                print(f"Agent: {block.text}")

        # Check stop reason
        if response.stop_reason == "end_turn":
            print("\nAgent resolved the case without escalation.")
            break

        if response.stop_reason != "tool_use":
            print(f"\nUnexpected stop reason: {response.stop_reason}")
            break

        # Process tool calls
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        tool_results_for_api = []
        escalated = False

        for block in tool_use_blocks:
            print(f"  [tool] {block.name}({json.dumps(block.input)})")

            if block.name == "escalate_to_human":
                # Build the handoff package before escalating
                handoff = await build_handoff(
                    client=client,
                    reason=block.input["reason"],
                    conversation_history=messages,
                    tool_results=tool_results_log
                )
                ticket_id = escalate(handoff)
                tool_results_for_api.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps({
                        "ticket_id": ticket_id,
                        "status": "escalated",
                        "message": "A human agent will follow up shortly."
                    })
                })
                escalated = True
            else:
                result = run_tool(block.name, block.input)
                print(f"  [result] {result}")
                tool_results_log.append({
                    "tool": block.name,
                    "input": block.input,
                    "result": json.loads(result)
                })
                tool_results_for_api.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

        # Append assistant turn + tool results to history
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results_for_api})

        if escalated:
            break


async def main():
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:
        await run_agent(
            client,
            "I was charged twice on March 12 for order ORD-99812. "
            "I need a refund for the duplicate charge of $142."
        )


if __name__ == "__main__":
    asyncio.run(main())
