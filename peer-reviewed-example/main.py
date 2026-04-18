import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
import json
import textwrap

load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-haiku-4-5-20251001"

GENERATION_PROMPT = """Generate 5 JLPT N5 vocabulary practice questions in multiple-choice format.
Each question tests one vocabulary word. Include 4 options (A-D), one correct answer, and a brief explanation.

Return ONLY a JSON array in this exact format, no other text:
[
  {
    "word": "日本語",
    "reading": "にほんご",
    "question": "What does 日本語 (にほんご) mean?",
    "options": {
      "A": "Japanese language",
      "B": "Japanese person",
      "C": "Japanese food",
      "D": "Japanese culture"
    },
    "correct": "A",
    "explanation": "日本語 means 'Japanese language'. 日本 = Japan, 語 = language."
  }
]"""

REVIEW_PROMPT = """Review these JLPT N5 vocabulary questions critically. Check each for:
1. Accuracy — are definitions, readings, and correct answers right?
2. Level appropriateness — is the vocabulary genuinely N5 level?
3. Distractor quality — are the wrong answers plausible but clearly wrong?
4. Any errors in furigana (readings)?

Rate each question 1–5 and give an overall verdict with a total score out of 25."""


def print_section(title: str, width: int = 64):
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def wrap(text: str, indent: int = 0) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=70, initial_indent=prefix, subsequent_indent=prefix)


def generate_questions(client: Anthropic) -> tuple[str, list[dict]]:
    """Generate JLPT N5 questions. Returns (raw_json, generation_messages)."""
    generation_messages = [{"role": "user", "content": GENERATION_PROMPT}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=generation_messages,
    )
    raw_json = response.content[0].text
    return raw_json, generation_messages


def self_review(client: Anthropic, generation_messages: list[dict], questions_json: str) -> str:
    """
    CASE 1 — BIASED: Continue the same conversation.
    The model has full context of having generated these questions.
    It is anchored to its own reasoning and prior choices.
    """
    messages = generation_messages + [
        {"role": "assistant", "content": questions_json},
        {"role": "user", "content": REVIEW_PROMPT},
    ]

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=messages,
    )
    return response.content[0].text


def peer_review(client: Anthropic, questions_json: str) -> str:
    """
    CASE 2 — UNBIASED: Completely fresh context.
    The model sees only the finished questions with no memory of generating them.
    It evaluates as an independent peer reviewer.
    """
    messages = [
        {
            "role": "user",
            "content": (
                "You are a senior Japanese language instructor reviewing JLPT N5 "
                "practice questions submitted by a colleague for quality control.\n\n"
                f"Questions to review:\n{questions_json}\n\n"
                f"{REVIEW_PROMPT}"
            ),
        }
    ]

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=messages,
    )
    return response.content[0].text


def main():
    client = Anthropic(
        # This is the default and can be omitted
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )

    print_section("JLPT N5 Question Review: Self vs Peer")
    print(wrap(
        "This example demonstrates how multi-turn context creates reviewer bias. "
        "Case 1: the same model that generated the questions reviews them in the same "
        "conversation (anchored to its own reasoning). "
        "Case 2: a fresh context with no generation history reviews the identical questions."
    ))

    # ── Generate questions ──────────────────────────────────────────────────
    print_section("STEP 1 — Generating JLPT N5 Questions")
    questions_json, generation_messages = generate_questions(client)

    try:
        questions = json.loads(questions_json)
        print(f"  Generated {len(questions)} questions.\n")
        for i, q in enumerate(questions, 1):
            print(f"  Q{i}: {q['word']} ({q['reading']}) — correct: {q['correct']}")
    except json.JSONDecodeError:
        print("  (Could not parse JSON for preview — continuing with raw output)")

    # ── Case 1: self-review ─────────────────────────────────────────────────
    print_section("CASE 1 — Self-Review  [SAME CONTEXT / BIASED]")
    print(wrap(
        "The model continues the conversation in which it generated the questions. "
        "It carries full memory of its own reasoning, word choices, and intent — "
        "making it psychologically anchored to approve what it already committed to."
    ))
    print()
    self_result = self_review(client, generation_messages, questions_json)
    print(self_result)

    # ── Case 2: peer-review ─────────────────────────────────────────────────
    print_section("CASE 2 — Peer Review  [FRESH CONTEXT / INDEPENDENT]")
    print(wrap(
        "A brand-new request with no prior messages. The model has no knowledge "
        "of having generated these questions, so it evaluates them as an outside "
        "reviewer would — without anchoring bias."
    ))
    print()
    peer_result = peer_review(client, questions_json)
    print(peer_result)

    # ── Key insight ─────────────────────────────────────────────────────────
    print_section("KEY INSIGHT")
    insights = [
        ("Self-Review (Case 1)",
         "The model remembers generating these questions and is anchored to its "
         "original choices. It tends to rationalise rather than critique, giving "
         "higher scores and fewer objections."),
        ("Peer Review (Case 2)",
         "With no generation context, the model approaches the questions as a "
         "fresh evaluator. It is more likely to flag ambiguous distractors, "
         "level mismatches, or reading errors."),
        ("The Fix",
         "For any AI-generated content that requires quality control, always use "
         "a separate context (new messages array, separate call, or separate model "
         "instance) for the validation step. Never ask the generator to grade its "
         "own output in the same conversation."),
    ]
    for label, text in insights:
        print(f"\n  [{label}]")
        print(wrap(text, indent=4))
    print()


if __name__ == "__main__":
    main()
