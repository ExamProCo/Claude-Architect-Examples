import os
from pathlib import Path
from dotenv import load_dotenv
import json
import anthropic

load_dotenv(Path(__file__).parent.parent / ".env")
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"),)

# Input: raw support ticket (unstructured)
raw_ticket = {
    "from": "angry.customer@example.com",
    "subject": "URGENT - Can't access my account and billing charged twice!!!",
    "body": (
        "I have been trying to log in for the past 3 days and keep getting "
        "'invalid credentials'. Your system reset my password without telling me. "
        "On top of that I was charged $49.99 TWICE this month. I need this fixed "
        "immediately or I'm disputing both charges with my bank. This is unacceptable."
    ),
    "received_at": "2026-04-18T09:14:00Z",
}

tools = [
    {
        "name": "submit_triage",
        "description": "Submit a structured triage record for a support ticket.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Generated ticket ID in format TKT-XXXXXX",
                },
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                },
                "category": {
                    "type": "string",
                    "enum": ["billing", "authentication", "technical", "account", "other"],
                },
                "secondary_category": {
                    "type": "string",
                    "enum": ["billing", "authentication", "technical", "account", "other", "none"],
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["very_frustrated", "frustrated", "neutral", "satisfied"],
                },
                "churn_risk": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "summary": {
                    "type": "string",
                    "description": "One-sentence summary of the issue",
                },
                "suggested_response": {
                    "type": "string",
                    "description": "Draft reply to send to the customer",
                },
                "escalate_to_billing": {"type": "boolean"},
                "escalate_to_engineering": {"type": "boolean"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant tags for routing and search",
                },
            },
            "required": [
                "ticket_id",
                "priority",
                "category",
                "secondary_category",
                "sentiment",
                "churn_risk",
                "summary",
                "suggested_response",
                "escalate_to_billing",
                "escalate_to_engineering",
                "tags",
            ],
            "additionalProperties": False,
        },
    }
]


def submit_triage(args: dict) -> str:
    print("\nOUTPUT — TRIAGE RECORD (received by tool)")
    print("=" * 52)
    print(json.dumps(args, indent=2))
    return json.dumps({"status": "submitted", "ticket_id": args["ticket_id"]})


def run():
    print("INPUT — RAW SUPPORT TICKET")
    print("=" * 52)
    print(json.dumps(raw_ticket, indent=2))

    messages = [
        {
            "role": "user",
            "content": f"Triage this support ticket:\n\n{json.dumps(raw_ticket, indent=2)}",
        }
    ]

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system="You are a support triage engine. Analyze incoming support tickets and call submit_triage with a fully structured triage record.",
            tools=tools,
            tool_choice={"type": "auto"},
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\n[calling tool: {block.name}]")
                    print(f"[tool input]: {json.dumps(block.input, indent=2)}")
                    result = submit_triage(block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            break


run()
