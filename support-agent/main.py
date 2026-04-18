import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv
import anthropic

load_dotenv(Path(__file__).parent.parent / ".env")
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"),)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from sdk_parser import log_message


class EscalationState(Enum):
    BOT_HANDLING = "bot_handling"
    ESCALATION_TRIGGERED = "escalation_triggered"
    HUMAN_QUEUE = "human_queue"
    HUMAN_ACTIVE = "human_active"
    RESOLVED = "resolved"


@dataclass
class SessionContext:
    state: EscalationState = EscalationState.BOT_HANDLING
    turn_count: int = 0
    escalation_reason: str = ""
    messages: list = field(default_factory=list)


MAX_BOT_TURNS = 6

SYSTEM_PROMPT = """You are a customer support agent for ExamPro Training Inc, a tech education platform offering self-paced courses.

You handle the following types of requests:
1. Refunds - process refund requests for course purchases
2. Course swaps - swap a purchased course for a different one
3. Confirmation emails - resend purchase/enrollment confirmation emails
4. Platform bugs - log bugs such as incorrect star counts or UI issues
5. Content problems - report issues like stale content or missing audio/video
6. Business development - route partnership and BD inquiries appropriately
7. GDPR requests - handle data deletion and data export requests

Always be polite, empathetic, and professional. Gather necessary information before taking action.
When you take an action, confirm the outcome to the customer.

## Multiple Matches — Always Ask for Clarification

If a tool returns multiple matching records (e.g., multiple orders or accounts for the same email), do NOT guess or pick one based on heuristics. Ask the customer for an additional identifier to pinpoint the correct record (e.g., order date, course name, last 4 digits of payment card).

Example:
Tool result: "Multiple orders found for jane@example.com: ORD-001 (AWS course, Jan 3), ORD-002 (Azure course, Jan 10)"
Agent: "I found two orders on your account. Could you confirm which course this is about — the AWS course from January 3rd or the Azure course from January 10th?"

## Handling Customer Frustration

When a customer expresses frustration or dissatisfaction but does NOT explicitly ask for a human, acknowledge the frustration and offer to resolve the issue. Only escalate if they explicitly reiterate a preference for a human agent after you have offered to help.

Example — frustrated but no human request:
Customer: "This is ridiculous, I've been waiting three weeks for my refund!"
Agent: "I'm really sorry — a three-week wait is absolutely not okay. Let me pull up your order right now and get this sorted. What's your order ID?"

Example — frustrated AND asks for human (offer resolution first):
Customer: "I want to speak to a real person, this bot is useless."
Agent: "I completely understand your frustration, and I'm sorry the experience hasn't been smooth. I genuinely want to fix this for you — could you tell me what the issue is and I'll resolve it directly? If you'd still prefer a human after hearing what I can do, I'll connect you right away."

Example — customer reiterates preference after offer:
Customer: "No, I still want a human."
Agent: [calls escalate_to_human immediately, priority="normal"]

## Explicit Human Agent Requests (No Frustration Context)

If a customer's very first message — or a clear standalone message — is simply a request to speak with a human, call `escalate_to_human` immediately. Do NOT attempt to investigate or offer resolution first.

Example:
Customer: "Hi, can I please speak with a human agent?"
Agent: [calls escalate_to_human immediately, priority="normal"]

Example:
Customer: "I need to talk to a real person about my account."
Agent: [calls escalate_to_human immediately, priority="normal"]

## Policy Ambiguity — Escalate Rather Than Improvise

If a customer's request is not covered by your defined capabilities, or falls in a grey area the policy does not address, escalate to a human rather than guessing or improvising a response.

Example — competitor price match (policy only covers own-site price adjustments):
Customer: "I saw this course for $15 less on Udemy. Can you match that price?"
Agent: [calls escalate_to_human — competitor price matching is not a defined capability]

Example — account merge (not a defined capability):
Customer: "I have two ExamPro accounts and want to merge them into one."
Agent: [calls escalate_to_human — account merges are outside defined capabilities]

Example — own-site pricing correction (within policy):
Customer: "The course is listed at $49 on your site but I was charged $79."
Agent: [investigates with issue_refund / swap tools — billing error is within scope]

## Escalation Decision Matrix

ESCALATE immediately (call escalate_to_human without attempting resolution):
- Standalone explicit request for a human agent
- Legal threat, fraud claim, or chargeback dispute
- Request is completely outside your defined capabilities
- Policy is ambiguous or silent on the specific scenario
- Extreme distress (bereavement, medical emergency, safety concern)

OFFER RESOLUTION FIRST, escalate only if rebuffed:
- Customer is frustrated but issue is within your capabilities
- Customer asks for human while frustrated — acknowledge, offer to help, escalate if they insist

RESOLVE autonomously (use your tools):
- Refund for a clearly identified order
- Course swap with identifiable courses
- Missing confirmation email
- Reproducible platform bug (create ticket)
- Specific content issue (create ticket)
- Business development inquiry (route to BD team)
- GDPR data request"""

TOOLS = [
    {
        "name": "issue_refund",
        "description": "Issue a refund for a course purchase",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string", "description": "Customer's email address"},
                "order_id": {"type": "string", "description": "The order ID to refund"},
                "reason": {"type": "string", "description": "Reason for the refund"}
            },
            "required": ["customer_email", "order_id", "reason"]
        }
    },
    {
        "name": "swap_course",
        "description": "Swap a customer's purchased course for a different course",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string", "description": "Customer's email address"},
                "current_course_id": {"type": "string", "description": "Course ID they currently have"},
                "new_course_id": {"type": "string", "description": "Course ID they want instead"}
            },
            "required": ["customer_email", "current_course_id", "new_course_id"]
        }
    },
    {
        "name": "resend_confirmation_email",
        "description": "Resend the purchase/enrollment confirmation email to the customer",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string", "description": "Customer's email address"},
                "order_id": {"type": "string", "description": "The order ID for which to resend confirmation"}
            },
            "required": ["customer_email", "order_id"]
        }
    },
    {
        "name": "create_bug_ticket",
        "description": "Create a bug ticket for a platform issue",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the bug"},
                "description": {"type": "string", "description": "Detailed description of the bug"},
                "reported_by": {"type": "string", "description": "Customer's email address"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"], "description": "Bug severity level"}
            },
            "required": ["title", "description", "reported_by", "severity"]
        }
    },
    {
        "name": "create_content_issue_ticket",
        "description": "Create a ticket for a content problem in a course",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string", "description": "The course ID with the content issue"},
                "lesson_id": {"type": "string", "description": "The specific lesson or module ID with the issue"},
                "issue_type": {"type": "string", "enum": ["stale_content", "no_audio", "no_video", "broken_link", "other"], "description": "Type of content issue"},
                "description": {"type": "string", "description": "Description of the content problem"},
                "reported_by": {"type": "string", "description": "Customer's email address"}
            },
            "required": ["course_id", "issue_type", "description", "reported_by"]
        }
    },
    {
        "name": "route_business_development",
        "description": "Route a business development or partnership inquiry to the BD team",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Name of the person reaching out"},
                "contact_email": {"type": "string", "description": "Email of the person reaching out"},
                "company": {"type": "string", "description": "Their company name"},
                "inquiry_summary": {"type": "string", "description": "Summary of the BD opportunity or inquiry"}
            },
            "required": ["contact_email", "inquiry_summary"]
        }
    },
    {
        "name": "process_gdpr_request",
        "description": "Process a GDPR data deletion or data export request",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string", "description": "Customer's email address"},
                "request_type": {"type": "string", "enum": ["deletion", "export"], "description": "Type of GDPR request"},
                "notes": {"type": "string", "description": "Any additional notes about the request"}
            },
            "required": ["customer_email", "request_type"]
        }
    },
    {
        "name": "escalate_to_human",
        "description": "Escalate this conversation to a human support agent. Use when the customer requests a human, the issue is beyond your capabilities, or the customer is extremely frustrated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why this conversation is being escalated"},
                "summary": {"type": "string", "description": "Brief summary of the issue and what has been attempted so far"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Priority level for the human agent"}
            },
            "required": ["reason", "summary", "priority"]
        }
    }
]


def handle_tool_call(tool_name: str, tool_input: dict, ctx: SessionContext) -> str:
    if tool_name == "issue_refund":
        return f"[MOCK] Refund of course purchase issued successfully for order {tool_input['order_id']} to {tool_input['customer_email']}. Refund will appear within 5-10 business days."

    elif tool_name == "swap_course":
        return f"[MOCK] Course swap completed. {tool_input['customer_email']} has been moved from course {tool_input['current_course_id']} to course {tool_input['new_course_id']}. Enrollment confirmation sent."

    elif tool_name == "resend_confirmation_email":
        return f"[MOCK] Confirmation email for order {tool_input['order_id']} resent to {tool_input['customer_email']}."

    elif tool_name == "create_bug_ticket":
        ticket_id = "BUG-" + str(abs(hash(tool_input['title'])))[:6]
        return f"[MOCK] Bug ticket {ticket_id} created: '{tool_input['title']}' (severity: {tool_input['severity']}). Engineering team notified."

    elif tool_name == "create_content_issue_ticket":
        ticket_id = "CONTENT-" + str(abs(hash(tool_input['description'])))[:6]
        return f"[MOCK] Content issue ticket {ticket_id} created for course {tool_input['course_id']} ({tool_input['issue_type']}). Content team notified."

    elif tool_name == "route_business_development":
        return f"[MOCK] BD inquiry from {tool_input.get('contact_email')} forwarded to the business development team. They will follow up within 2 business days."

    elif tool_name == "process_gdpr_request":
        request_id = "GDPR-" + str(abs(hash(tool_input['customer_email'])))[:6]
        return f"[MOCK] GDPR {tool_input['request_type']} request {request_id} submitted for {tool_input['customer_email']}. Will be processed within 30 days per regulations."

    elif tool_name == "escalate_to_human":
        ctx.state = EscalationState.ESCALATION_TRIGGERED
        ctx.escalation_reason = tool_input["reason"]
        ticket_id = "ESC-" + str(abs(hash(tool_input["summary"])))[:6]
        return (
            f"[MOCK] Escalation ticket {ticket_id} created (priority: {tool_input['priority']}). "
            f"A human agent will be assigned shortly. Reason: {tool_input['reason']}"
        )

    return f"[MOCK] Tool '{tool_name}' executed with input: {tool_input}"


def run_turn(ctx: SessionContext, customer_message: str) -> bool:
    """Run one customer turn. Returns False if the session should end."""
    if ctx.state in (EscalationState.HUMAN_ACTIVE, EscalationState.RESOLVED):
        print("\n[System] This conversation has been handed off to a human agent. Bot is offline.\n")
        return False

    ctx.turn_count += 1
    print(f"\nYou: {customer_message}\n")

    # Auto-escalate on turn limit (safety net — model handles human requests naturally)
    if ctx.turn_count > MAX_BOT_TURNS and ctx.state == EscalationState.BOT_HANDLING:
        ctx.state = EscalationState.ESCALATION_TRIGGERED
        ctx.escalation_reason = f"Conversation exceeded {MAX_BOT_TURNS} turns without resolution"

    if ctx.state == EscalationState.ESCALATION_TRIGGERED:
        _handle_handoff(ctx)
        return False

    print("Agent: ", end="", flush=True)
    ctx.messages.append({"role": "user", "content": customer_message})

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=ctx.messages,
        )

        for block in response.content:
            if hasattr(block, "text"):
                print(block.text, end="", flush=True)

        if response.stop_reason == "end_turn":
            ctx.messages.append({"role": "assistant", "content": response.content})
            break

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            ctx.messages.append({"role": "assistant", "content": response.content})
            break

        ctx.messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool in tool_use_blocks:
            result = handle_tool_call(tool.name, tool.input, ctx)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool.id,
                "content": result,
            })

        ctx.messages.append({"role": "user", "content": tool_results})

        # If escalation was triggered during tool handling, let the model respond then exit
        if ctx.state == EscalationState.ESCALATION_TRIGGERED:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=ctx.messages,
            )
            for block in response.content:
                if hasattr(block, "text"):
                    print(block.text, end="", flush=True)
            ctx.messages.append({"role": "assistant", "content": response.content})
            break

    print("\n")

    if ctx.state == EscalationState.ESCALATION_TRIGGERED:
        _handle_handoff(ctx)
        return False

    return True


def _handle_handoff(ctx: SessionContext):
    ctx.state = EscalationState.HUMAN_QUEUE
    print("\n" + "=" * 60)
    print("  ESCALATION: Transferring to human agent")
    print("=" * 60)
    print(f"  Reason   : {ctx.escalation_reason}")
    print(f"  Turn #   : {ctx.turn_count}")
    print(f"  State    : {ctx.state.value}")
    print("=" * 60)
    print("\n[System] You have been placed in the human support queue.")
    print("[System] A support agent will be with you shortly. This bot session has ended.\n")
    ctx.state = EscalationState.HUMAN_ACTIVE


def main():
    print("ExamPro Support Agent (type 'quit' or Ctrl+C to exit)\n")
    print(f"[System] Bot will auto-escalate after {MAX_BOT_TURNS} turns or on request.\n")
    ctx = SessionContext()

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "bye"):
            print("Goodbye!")
            break

        should_continue = run_turn(ctx, user_input)
        if not should_continue:
            break


main()
