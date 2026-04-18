import os
import re
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
                    "description": "Generated ticket ID in format TKT-XXXXXX (6 digits only, e.g. TKT-004821)",
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
                    "description": "One-sentence summary between 20 and 40 characters",
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
                    "description": "At least 3 relevant tags for routing and search",
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

MAX_RETRIES = 3


def validate_triage(args: dict) -> list[str]:
    """Return a list of validation error strings; empty list means valid."""
    errors = []

    # ticket_id must be TKT- followed by exactly 6 digits
    if not re.fullmatch(r"TKT-\d{6}", args.get("ticket_id", "")):
        errors.append(
            f"ticket_id '{args.get('ticket_id')}' is invalid — must be TKT- followed by "
            "exactly 6 digits (e.g. TKT-004821). Letters and mixed formats are not allowed."
        )

    # summary must be 20–40 characters
    summary = args.get("summary", "")
    if not (20 <= len(summary) <= 40):
        errors.append(
            f"summary is {len(summary)} characters — must be between 20 and 40 characters. "
            f"Current value: '{summary}'"
        )

    # tags must contain at least 3 items, each using snake_case (underscores, no hyphens)
    tags = args.get("tags", [])
    if len(tags) < 3:
        errors.append(
            f"tags has {len(tags)} item(s) — must contain at least 3 tags. "
            f"Current tags: {tags}"
        )
    hyphenated = [t for t in tags if "-" in t]
    if hyphenated:
        errors.append(
            f"tags must use snake_case (underscores), not hyphens. "
            f"Fix these: {hyphenated} — e.g. 'account-lockout' → 'account_lockout'"
        )

    # when ticket contains both billing and auth issues, secondary_category must not be "none"
    body_lower = raw_ticket["body"].lower()
    has_billing = "charged" in body_lower or "billing" in body_lower
    has_auth = "log in" in body_lower or "credentials" in body_lower or "password" in body_lower
    if has_billing and has_auth and args.get("secondary_category") == "none":
        errors.append(
            "secondary_category is 'none' but the ticket clearly contains both a billing issue "
            "and an authentication issue — set secondary_category to the second issue type."
        )

    return errors


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

    attempt = 0

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
            all_valid = True

            for block in response.content:
                if block.type != "tool_use":
                    continue

                attempt += 1
                print(f"\n[attempt {attempt}] calling tool: {block.name}")
                print(json.dumps(block.input, indent=2))

                errors = validate_triage(block.input)

                if errors:
                    all_valid = False
                    error_text = (
                        f"Validation failed ({len(errors)} error(s)). "
                        "Fix all issues and call submit_triage again:\n"
                        + "\n".join(f"  • {e}" for e in errors)
                    )
                    print(f"\n[validation FAILED on attempt {attempt}]")
                    for e in errors:
                        print(f"  • {e}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": error_text,
                    })
                else:
                    print(f"\n[validation PASSED on attempt {attempt}]")
                    result = submit_triage(block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

            if all_valid:
                break

            if attempt >= MAX_RETRIES:
                print(f"\n[max retries ({MAX_RETRIES}) reached — aborting]")
                break


run()
