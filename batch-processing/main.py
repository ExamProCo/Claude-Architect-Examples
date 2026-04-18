import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

load_dotenv(Path(__file__).parent.parent / ".env")
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

BATCH_STATE_FILE = Path(__file__).parent / ".batch_state.json"

tickets = [
    {
        "id": "ticket-001",
        "from": "angry.customer@example.com",
        "subject": "URGENT - Can't access my account and billing charged twice!!!",
        "body": (
            "I have been trying to log in for the past 3 days and keep getting "
            "'invalid credentials'. Your system reset my password without telling me. "
            "On top of that I was charged $49.99 TWICE this month. I need this fixed "
            "immediately or I'm disputing both charges with my bank. This is unacceptable."
        ),
        "received_at": "2026-04-18T09:14:00Z",
    },
    {
        "id": "ticket-002",
        "from": "curious.user@example.com",
        "subject": "How do I export my data?",
        "body": "Hi, I'd like to export all my data from the platform. Is there a way to do this? Thanks!",
        "received_at": "2026-04-18T09:30:00Z",
    },
]

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


def submit():
    print("INPUT — RAW SUPPORT TICKETS")
    print("=" * 52)
    for ticket in tickets:
        print(f"  [{ticket['id']}] {ticket['subject']}")

    requests = [
        Request(
            custom_id=ticket["id"],
            params=MessageCreateParamsNonStreaming(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system="You are a support triage engine. Analyze incoming support tickets and call submit_triage with a fully structured triage record.",
                tools=tools,
                tool_choice={"type": "any"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Triage this support ticket:\n\n{json.dumps(ticket, indent=2)}",
                    }
                ],
            ),
        )
        for ticket in tickets
    ]

    batch = client.messages.batches.create(requests=requests)
    BATCH_STATE_FILE.write_text(json.dumps({"batch_id": batch.id}))

    print(f"\nBatch submitted: {batch.id}")
    print(f"Status: {batch.processing_status}")
    print(f"State saved to {BATCH_STATE_FILE.name}")
    print("\nRun `python main.py check` to retrieve results when ready.")


def check():
    if not BATCH_STATE_FILE.exists():
        print("No batch in progress. Run `python main.py submit` first.")
        return

    state = json.loads(BATCH_STATE_FILE.read_text())
    batch_id = state["batch_id"]
    batch = client.messages.batches.retrieve(batch_id)

    print(f"Batch: {batch_id}")
    print(f"Status: {batch.processing_status}")
    print(f"  processing={batch.request_counts.processing}  succeeded={batch.request_counts.succeeded}  errored={batch.request_counts.errored}")

    if batch.processing_status != "ended":
        print("\nNot done yet — check back later.")
        return

    print("\nOUTPUT — TRIAGE RECORDS")
    print("=" * 52)
    for result in client.messages.batches.results(batch_id):
        if result.result.type == "succeeded":
            for block in result.result.message.content:
                if block.type == "tool_use" and block.name == "submit_triage":
                    print(f"\n[{result.custom_id}]")
                    print(json.dumps(block.input, indent=2))
        else:
            err = result.result.error
            print(f"\n[{result.custom_id}] ERROR ({err.type})")

    BATCH_STATE_FILE.unlink()


def run_and_wait():
    submit()
    state = json.loads(BATCH_STATE_FILE.read_text())
    batch_id = state["batch_id"]
    print("\nPolling every 5s...\n")
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        print(f"  processing={batch.request_counts.processing} remaining...")
        time.sleep(5)
    check()


command = sys.argv[1] if len(sys.argv) > 1 else "run"

if command == "submit":
    submit()
elif command == "check":
    check()
elif command == "run":
    run_and_wait()
else:
    print(f"Usage: python main.py [submit|check|run]")
    print("  submit  — fire the batch and exit immediately")
    print("  check   — check status / print results if done")
    print("  run     — submit and wait (original blocking behaviour)")
