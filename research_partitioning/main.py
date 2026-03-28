import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Use case: Job Application Screener — 

# ---------------------------------------------------------------------------

model = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Spoke system prompts — 
# ---------------------------------------------------------------------------

SCREENING_AGENT_PROMPT = """You are a specialist hiring analyst. You will be given a specific
screening question about a candidate along with the job posting and resume.

Answer the question in 2-3 focused sentences. Be concrete and specific to this candidate."""

EVALUATION_AGENT_PROMPT = """You are a screening coverage evaluator. Review the screening
findings collected so far and identify gaps.

Return ONLY a valid JSON object with these fields:
  "coverage_score": integer 0-10 (10 = complete coverage of all important hiring dimensions)
  "gaps": list of strings describing specific missing dimensions or unanswered questions
  "sufficient": boolean (true if a confident final recommendation can be made right now)
  "rationale": one sentence explaining the coverage score

No markdown fences, no commentary — only the JSON object."""

# ---------------------------------------------------------------------------
# Tool schema — screening spoke + refinement loop tools
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
    },
    {
        "name": "evaluate_coverage",
        "description": (
            "Evaluate the current screening findings for completeness and identify gaps. "
            "Call after the initial partition agents have all reported, and again after "
            "each refinement round. Returns a coverage score, list of gaps, and whether "
            "coverage is now sufficient to make a final recommendation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_findings": {
                    "type": "string",
                    "description": "Summary of all screening results collected so far",
                }
            },
            "required": ["current_findings"],
        },
    },
    {
        "name": "submit_final",
        "description": (
            "Submit the final HIRE / MAYBE / PASS recommendation. "
            "Only call this when evaluate_coverage has confirmed sufficient coverage, "
            "or when the refinement iteration limit has been reached."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recommendation": {
                    "type": "string",
                    "description": "Final recommendation: HIRE, MAYBE, or PASS with full justification",
                }
            },
            "required": ["recommendation"],
        },
    },
]


# ---------------------------------------------------------------------------
# Partition planner — generates non-overlapping screening scopes as JSON
# before any agent is invoked, so the coordinator can route without overlap.
# ---------------------------------------------------------------------------

PARTITION_PLANNER_PROMPT = """You are a screening partition planner. Given a job posting and resume,
output a JSON array of non-overlapping screening partitions.

Each partition object must have:
  "agent"  — a short unique name  (e.g. "technical_depth_agent")
  "scope"  — an object with:
      "topic"   — one sentence describing what this partition evaluates
      "cover"   — list of specific aspects IN scope
      "exclude" — list of aspects explicitly OUT of scope (prevents overlap with other partitions)

Rules:
- Design partitions so that together they cover all relevant hiring questions
- No two partitions may share the same "cover" aspects
- Only include partitions that are genuinely needed for THIS candidate-role pair
- Return ONLY valid JSON — no markdown fences, no commentary"""


async def generate_partitions(client, job_posting: str, resume: str) -> list[dict]:
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=PARTITION_PLANNER_PROMPT,
        messages=[{"role": "user", "content": (
            f"Generate screening partitions for this application.\n\n"
            f"JOB POSTING:\n{job_posting}\n\n"
            f"RESUME:\n{resume}"
        )}],
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if the model adds them anyway
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines()
            if not line.startswith("```")
        ).strip()
    return json.loads(text)


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


async def call_evaluation_agent(client, current_findings: str) -> dict:
    r = await client.messages.create(
        model=model,
        max_tokens=400,
        system=EVALUATION_AGENT_PROMPT,
        messages=[{"role": "user", "content": (
            f"Evaluate coverage of these screening findings:\n\n{current_findings}"
        )}],
    )
    text = r.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines()
            if not line.startswith("```")
        ).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# DYNAMIC coordinator — true dynamic selection
#
# The coordinator reads the candidate + role first, then decides WHICH
# dimensions actually matter for this specific case. It skips obvious checks
# and only invokes agents where there is real uncertainty or risk.
#
# Routing logic examples:
#   Strong technical match, standard background → skip keyword scan;
#     focus on depth, growth trajectory, and culture fit
#   Career changer / non-traditional path → prioritize transferable skills;
#     de-emphasize raw keyword match
#   Senior / leadership role → add team dynamics, strategic scope
#   Obvious red flags present → address those first, then compensating strengths
#   Niche hard-to-fill role → deep-dive on the specific requirements
#
# The key insight: not every candidate needs every check. Running fewer,
# better-targeted agents produces a sharper recommendation faster.
# ---------------------------------------------------------------------------

DYNAMIC_COORDINATOR = """You are a job application screening coordinator with a refinement loop.

You will receive pre-planned screening PARTITIONS as JSON. Follow these phases:

PHASE 1 — Initial Screening:
Invoke exactly one screening_agent call per partition. Formulate each question so it stays
strictly within that partition's "cover" list and avoids its "exclude" list.

PHASE 2 — Evaluate Coverage:
After all initial partition agents have reported, call evaluate_coverage with a plain-text
summary of all findings collected so far. The evaluator will return a coverage score,
identified gaps, and whether coverage is sufficient.

PHASE 3 — Refinement (max 3 iterations):
If evaluate_coverage returns sufficient=false and gaps exist:
  - Invoke screening_agent calls to fill only the identified gaps (one call per gap).
  - Then call evaluate_coverage again with the updated findings summary.
  - Repeat until sufficient=true or 3 refinement iterations are exhausted.

PHASE 4 — Submit Final:
Call submit_final with your HIRE / MAYBE / PASS recommendation and full justification
once evaluate_coverage confirms sufficient=true, or once you have reached the iteration limit.

Do NOT call submit_final before running evaluate_coverage at least once."""


async def run_coordinator(
    client, coordinator_prompt: str, label: str,
    job_posting: str, resume: str
) -> list[str]:
    print(f"\n{'='*60}")
    print(label)
    print(f"{'='*60}")

    # Step 1 — generate non-overlapping partitions and show them to the human
    print("\nGenerating screening partitions...\n")
    partitions = await generate_partitions(client, job_posting, resume)
    print("Screening partitions:")
    print(json.dumps(partitions, indent=2))
    print()

    # Verify partitions have no duplicate cover items across agents
    all_cover: list[str] = []
    for p in partitions:
        for item in p.get("scope", {}).get("cover", []):
            if item.lower() in [c.lower() for c in all_cover]:
                print(f"  [OVERLAP WARNING] '{item}' appears in multiple partitions")
            all_cover.append(item)

    print("Screening angles delegated:\n")

    # Step 2 — pass partitions to the coordinator so it routes correctly
    partition_context = (
        "SCREENING PARTITIONS (non-overlapping scopes pre-planned for this candidate):\n"
        + json.dumps(partitions, indent=2)
    )

    messages = [{"role": "user", "content": (
        f"Please screen this application using the partitions below.\n\n"
        f"{partition_context}\n\n"
        f"JOB POSTING:\n{job_posting}\n\n"
        f"RESUME:\n{resume}"
    )}]

    delegated: list[str] = []
    step = 0
    refinement_iter = 0
    MAX_REFINEMENTS = 3

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
            if final:
                print(f"\nFinal recommendation:\n{final}")
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "screening_agent":
                    question = block.input["question"]
                    delegated.append(question)
                    print(f"  [{len(delegated):2d}] {question}")
                    result = await call_screening_agent(client, question, job_posting, resume)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                elif block.name == "evaluate_coverage":
                    refinement_iter += 1
                    print(f"\n[Evaluating coverage — iteration {refinement_iter}]")
                    evaluation = await call_evaluation_agent(
                        client, block.input["current_findings"]
                    )
                    score = evaluation.get("coverage_score", "?")
                    gaps = evaluation.get("gaps", [])
                    sufficient = evaluation.get("sufficient", False)
                    print(f"  Coverage score: {score}/10")
                    if gaps:
                        print(f"  Gaps: {', '.join(gaps)}")
                    else:
                        print("  No gaps identified.")
                    print(f"  Sufficient: {sufficient}")

                    # If we've hit the refinement cap, force sufficient=true
                    if refinement_iter >= MAX_REFINEMENTS and not sufficient:
                        print(f"  [Refinement limit reached — proceeding to final]")
                        evaluation["sufficient"] = True

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(evaluation),
                    })

                elif block.name == "submit_final":
                    recommendation = block.input["recommendation"]
                    print(f"\nFinal recommendation:\n{recommendation}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Recommendation submitted.",
                    })
                    messages += [
                        {"role": "assistant", "content": response.content},
                        {"role": "user",      "content": tool_results},
                    ]
                    return delegated

            messages += [
                {"role": "assistant", "content": response.content},
                {"role": "user",      "content": tool_results},
            ]
    else:
        print("[WARN] Reached step limit.")

    return delegated


def coverage_report(dynamic_qs: list[str]) -> None:
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
    print("COVERAGE REPORT")
    print(f"{'='*60}")
    print(f"\n  Dynamic coordinator:  {len(dynamic_qs):2d} screening angles\n")
    print(f"  {'Dimension':<45} {'Covered':>8}")
    print(f"  {'-'*45} {'-'*8}")

    for label, keywords in dimensions:
        in_dynamic = covered(dynamic_qs, keywords)
        print(f"  {label:<45} {'✓' if in_dynamic else '✗':>8}")

    print()
    print("  DYNAMIC  — reads the candidate first, routes to relevant checks only.")
    print("             Skips obvious angles, adds targeted ones where risk exists.")
    print("             Fewer agents, sharper signal.")


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
        print("The coordinator reads the candidate first, then routes to relevant checks only.")

        dynamic_qs = await run_coordinator(
            client, DYNAMIC_COORDINATOR,
            "DYNAMIC COORDINATOR  (reads candidate first, routes to relevant checks only)",
            job_posting, resume,
        )

        coverage_report(dynamic_qs)


asyncio.run(main())
