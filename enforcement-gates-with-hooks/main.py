import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

from gate import (
    EnforcementGate,
    max_calls_listener,
    no_duplicate_listener,
    required_dimensions_listener,
)

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Use case: Job Application Screener — Narrow vs. Better Coordinator Prompts
#
# coordinator_agent_basic shows a fixed hub & spoke pipeline:
#   coordinator tells spokes exactly what to run (keyword_scanner,
#   deep_evaluator, red_flag_detector, score_aggregator) in a fixed order.
#
# The problem: the coordinator never asks itself what it might be missing.
# It runs the same three checks on every candidate regardless of context.
#
# The fix: give the coordinator a self-reflection step before it delegates.
#   1. Generate an initial list of screening angles
#   2. Ask: what perspectives, stakeholders, or dimensions am I missing?
#   3. Add subtasks to cover the gaps
#   4. Only then begin delegating
#
# With a domain-specific checklist, the coordinator will surface angles it
# would never reach on the first pass: compensation fit, team dynamics,
# long-term potential, role-specific risks, and so on.
# ---------------------------------------------------------------------------

model = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Spoke system prompts — same for both coordinators
# ---------------------------------------------------------------------------

SCREENING_AGENT_PROMPT = """You are a specialist hiring analyst. You will be given a specific
screening question about a candidate along with the job posting and resume.

Answer the question in 2-3 focused sentences. Be concrete and specific to this candidate."""

# ---------------------------------------------------------------------------
# Tool schema — a single flexible spoke both coordinators use
# ---------------------------------------------------------------------------

tools = [
    {
        "name": "screening_agent",
        "description": (
            "Runs a specialist screening agent on one specific angle of candidate fit. "
            "Call once per screening dimension with a focused question. "
            "Each call receives the full job posting and resume."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The specific screening question to evaluate",
                }
            },
            "required": ["question"],
        },
    }
]


async def call_screening_agent(client, question: str, job_posting: str, resume: str) -> str:
    r = await client.messages.create(
        model=model,
        max_tokens=200,
        system=SCREENING_AGENT_PROMPT,
        messages=[{"role": "user", "content": (
            f"QUESTION: {question}\n\n"
            f"JOB POSTING:\n{job_posting}\n\n"
            f"RESUME:\n{resume}"
        )}],
    )
    return r.content[0].text


# ---------------------------------------------------------------------------
# NARROW coordinator — mirrors coordinator_agent_basic
#
# Tells the model exactly which checks to run. No gap-checking.
# Works well when you know in advance every angle that matters.
# Breaks down when the candidate or role has unusual characteristics
# that fall outside the fixed list.
# ---------------------------------------------------------------------------

NARROW_COORDINATOR = """You are a job application screening coordinator.

Screen this candidate by running the following checks using the screening_agent tool:
1. Keyword match — do required skills appear in the resume?
2. Experience depth — does the candidate's background match the seniority level?
3. Red flags — are there disqualifying signals (gaps, job hopping, seniority mismatch)?

After all checks, synthesize a final HIRE / MAYBE / PASS recommendation."""

# ---------------------------------------------------------------------------
# BETTER coordinator — same domain, richer prompt
#
# The coordinator generates its own screening plan, then audits it for gaps
# before delegating. The domain-specific checklist names the dimensions
# a hiring coordinator is most likely to overlook on the first pass.
# ---------------------------------------------------------------------------

BETTER_COORDINATOR = """You are a job application screening coordinator.

When screening a candidate:

1. Generate an initial list of screening angles
2. Ask yourself: what perspectives, stakeholders, or dimensions are missing?
3. Add screening angles to cover those gaps
4. Only then begin delegating to the screening_agent tool

For hiring decisions specifically, consider:
- technical skills AND soft skills / working style
- hard requirements AND nice-to-haves — and the trade-off between them
- what the candidate has done AND how they've grown over time
- fit for the role today AND potential to grow into expanded scope
- risks and red flags AND compensating strengths that offset them
- the candidate's perspective — compensation expectations, motivations, timeline
- team and culture fit, not just individual contributor capability

After all screening angles are covered, synthesize a final HIRE / MAYBE / PASS recommendation."""


async def run_coordinator(
    client, coordinator_prompt: str, label: str,
    job_posting: str, resume: str,
    gate: EnforcementGate | None = None,
) -> list[str]:
    print(f"\n{'='*60}")
    print(label)
    print(f"{'='*60}")
    print("Screening angles delegated:\n")

    if gate:
        gate.reset()

    messages = [{"role": "user", "content": (
        f"Please screen this application.\n\n"
        f"JOB POSTING:\n{job_posting}\n\n"
        f"RESUME:\n{resume}"
    )}]

    delegated: list[str] = []
    step = 0

    while step < 30:
        step += 1
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=coordinator_prompt,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            final = next((b.text for b in response.content if hasattr(b, "text")), "")
            print(f"\nFinal recommendation:\n{final}")
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "screening_agent":
                    question = block.input["question"]

                    if gate:
                        # Gate fires pre_tool listeners, runs the tool, fires post_tool
                        # listeners — all internally. Loop just handles the outcome.
                        execution = await gate.execute(
                            tool_name  = block.name,
                            tool_input = block.input,
                            executor   = lambda q=question: call_screening_agent(
                                client, q, job_posting, resume
                            ),
                        )
                        if execution.blocked:
                            print(f"  [BLOCKED] {question}")
                            print(f"            {execution.reason}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"[GATE BLOCKED] {execution.reason}",
                                "is_error": True,
                            })
                            continue
                        result = execution.value
                    else:
                        result = await call_screening_agent(client, question, job_posting, resume)

                    delegated.append(question)
                    print(f"  [{len(delegated):2d}] {question}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages += [
                {"role": "assistant", "content": response.content},
                {"role": "user",      "content": tool_results},
            ]
    else:
        print("[WARN] Reached step limit.")

    if gate:
        print(f"\nGate summary:\n{gate.summary()}")

    return delegated


def coverage_report(narrow_qs: list[str], better_qs: list[str]) -> None:
    dimensions = [
        ("technical / hard skill match",           ["skill", "python", "fastapi", "keyword", "technical", "required"]),
        ("experience depth / seniority",            ["depth", "senior", "experience", "level", "scope"]),
        ("red flags / disqualifiers",               ["red flag", "gap", "hop", "disqualif", "concern"]),
        ("soft skills / working style",             ["soft", "communication", "collaborat", "working style", "team"]),
        ("growth trajectory / potential",           ["growth", "trajectory", "potential", "progression", "future"]),
        ("nice-to-haves and trade-offs",            ["nice", "trade", "bonus", "preferred", "optional"]),
        ("compensation / motivation / timeline",    ["compens", "salary", "motiv", "timeline", "expectation"]),
        ("team / culture fit",                      ["culture", "team fit", "team dynamic", "environment"]),
        ("compensating strengths for gaps",         ["compensat", "offset", "strength", "despite", "mitigat"]),
    ]

    def covered(qs: list[str], keywords: list[str]) -> bool:
        combined = " ".join(qs).lower()
        return any(kw in combined for kw in keywords)

    print(f"\n{'='*60}")
    print("COVERAGE COMPARISON")
    print(f"{'='*60}")
    print(f"\n  Narrow coordinator:  {len(narrow_qs):2d} screening angles")
    print(f"  Better coordinator:  {len(better_qs):2d} screening angles\n")
    print(f"  {'Dimension':<45} {'Narrow':>8} {'Better':>8}")
    print(f"  {'-'*45} {'-'*8} {'-'*8}")

    missed = 0
    for label, keywords in dimensions:
        in_narrow = covered(narrow_qs, keywords)
        in_better = covered(better_qs, keywords)
        if not in_narrow:
            missed += 1
        print(f"  {label:<45} {'✓' if in_narrow else '✗':>8} {'✓' if in_better else '✗':>8}")

    print(f"\n  Narrow coordinator missed {missed}/{len(dimensions)} dimensions.")
    print()
    print("  The fix is two additions to the coordinator prompt:")
    print()
    print('  1. The self-reflection step:')
    print('     "Ask yourself: what perspectives or dimensions are missing?')
    print('      Add screening angles to cover those gaps."')
    print()
    print('  2. A domain-specific checklist that names what hiring coordinators')
    print('     most commonly overlook on the first pass.')


async def main() -> None:
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:

        job_posting = """\
Title: Senior Python Backend Engineer
Required skills: Python (5+ years), FastAPI, PostgreSQL, Docker, REST API design
Nice to have: Kubernetes, Redis, system design at scale
Seniority: Senior (5-8 years total experience)"""

        resume = """\
Alex Chen — 7 years experience
2022–present: Backend Engineer, FinTech startup — Python, FastAPI, PostgreSQL, Docker
2019–2022:    Software Engineer, SaaS company — Python, Django, MySQL
2017–2019:    Junior Developer, agency — PHP, JavaScript
Skills: Python, FastAPI, PostgreSQL, Docker, REST APIs, some Redis
Education: B.Sc. Computer Science"""

        print("Candidate: Alex Chen — Senior Python Backend Engineer application")
        print()
        print("Both coordinators use the same screening_agent spoke.")
        print("The narrow coordinator is also gated with enforcement hooks.")
        print("Watch how blocked calls appear and how the model adapts.\n")

        # ── Enforcement gate for the NARROW coordinator ─────────────────────
        # Register listeners on named events. The gate fires them automatically
        # inside gate.execute() — the loop never touches pre/post logic directly.
        narrow_gate = (
            EnforcementGate()
            .on("pre_tool", max_calls_listener("screening_agent", max_n=7))
            .on("pre_tool", no_duplicate_listener("screening_agent", arg_key="question"))
            .on("pre_tool", required_dimensions_listener(
                tool_name="screening_agent",
                required_keywords=["soft skill", "communication", "compens", "salary", "motivation"],
                arg_key="question",
                enforce_after_n=3,
            ))
        )
        # ────────────────────────────────────────────────────────────────────

        narrow_qs = await run_coordinator(
            client, NARROW_COORDINATOR,
            "NARROW COORDINATOR  (fixed checklist, no gap-checking) + ENFORCEMENT GATE",
            job_posting, resume,
            gate=narrow_gate,
        )

        better_qs = await run_coordinator(
            client, BETTER_COORDINATOR,
            "BETTER COORDINATOR  (self-reflection + domain checklist, no gate)",
            job_posting, resume,
        )

        coverage_report(narrow_qs, better_qs)


asyncio.run(main())
