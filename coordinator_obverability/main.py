import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Use case: Job Application Screener — with full observability layer
# ---------------------------------------------------------------------------

model = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Fix 1 — Structured logger with timestamps and tagged event types
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("coordinator")

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Spoke system prompts
# ---------------------------------------------------------------------------

SCREENING_AGENT_PROMPT = """You are a specialist hiring analyst. You will be given a specific
screening question about a candidate along with the job posting and resume.

Your message will include a SCOPE header — answer ONLY within that scope.

Answer the question in 2-3 focused sentences. Be concrete and specific to this candidate."""

# ---------------------------------------------------------------------------
# Tool schemas — screening spoke + evaluate_coverage + submit_final
# ---------------------------------------------------------------------------

tools = [
    {
        "name": "screening_agent",
        "description": (
            "Runs a specialist screening agent on one specific angle of candidate fit. "
            "Call once per screening dimension with a focused question. "
            "Each call receives the full job posting and resume scoped to the partition."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partition_agent": {
                    "type": "string",
                    "description": "The partition agent name this question belongs to (from the partitions JSON)",
                },
                "question": {
                    "type": "string",
                    "description": "The specific screening question to evaluate",
                },
            },
            "required": ["partition_agent", "question"],
        },
    },
    # Fix 4 — evaluate_coverage: mid-run gap detection tool
    {
        "name": "evaluate_coverage",
        "description": (
            "Evaluate whether the screening findings so far are sufficient to make a "
            "confident recommendation. Call this after all partition agents have reported. "
            "Returns a coverage score, list of gaps, and whether the coverage is sufficient."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "findings_summary": {
                    "type": "string",
                    "description": "A brief summary of all screening findings collected so far",
                },
                "coverage_score": {
                    "type": "integer",
                    "description": "Coverage score 1-10 (10 = fully covered, no gaps)",
                },
                "gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of screening dimensions that still have unresolved uncertainty",
                },
                "sufficient": {
                    "type": "boolean",
                    "description": "True if coverage is sufficient to make a confident recommendation",
                },
            },
            "required": ["findings_summary", "coverage_score", "gaps", "sufficient"],
        },
    },
    # Fix 5 — submit_final: explicit exit gate
    {
        "name": "submit_final",
        "description": (
            "Submit the final hiring recommendation. Call this ONLY after evaluate_coverage "
            "returns sufficient=true (or after gap-filling follow-ups). "
            "This is the only valid way to conclude the screening."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["HIRE", "MAYBE", "PASS"],
                    "description": "The hiring recommendation",
                },
                "rationale": {
                    "type": "string",
                    "description": "2-4 sentence rationale integrating all screening findings",
                },
                "key_strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Top 2-3 candidate strengths",
                },
                "key_concerns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Top concerns or risks (empty list if none)",
                },
            },
            "required": ["verdict", "rationale", "key_strengths", "key_concerns"],
        },
    },
]


# ---------------------------------------------------------------------------
# Partition planner — generates non-overlapping screening scopes as JSON
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


# Fix 2 — error handling around partition generation
async def generate_partitions(client, job_posting: str, resume: str) -> list[dict]:
    try:
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
        text = response.content[0].text.strip() if response.content else ""
        if not text:
            raise ValueError("Partition planner returned empty response")
        # Strip markdown code fences if the model adds them anyway
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.splitlines()
                if not line.startswith("```")
            ).strip()
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.error("[ERROR] Partition planner returned invalid JSON: %s", exc)
        raise
    except Exception as exc:
        log.error("[ERROR] generate_partitions failed: %s", exc)
        raise


# Fix 6 — scope context: prepend partition header to spoke message
async def call_screening_agent(
    client, question: str, job_posting: str, resume: str,
    partition: dict | None = None,
) -> str:
    scope_header = ""
    if partition:
        scope = partition.get("scope", {})
        scope_header = (
            f"SCOPE (answer only within this boundary):\n"
            f"  Topic  : {scope.get('topic', '')}\n"
            f"  Cover  : {scope.get('cover', [])}\n"
            f"  Exclude: {scope.get('exclude', [])}\n\n"
        )
    try:
        r = await client.messages.create(
            model=model,
            max_tokens=200,
            system=SCREENING_AGENT_PROMPT,
            messages=[{"role": "user", "content": (
                f"{scope_header}"
                f"QUESTION: {question}\n\n"
                f"JOB POSTING:\n{job_posting}\n\n"
                f"RESUME:\n{resume}"
            )}],
        )
        return r.content[0].text if r.content else "[no response]"
    except Exception as exc:
        log.error("[ERROR] call_screening_agent failed for question '%s': %s", question, exc)
        return f"[ERROR: {exc}]"


# ---------------------------------------------------------------------------
# DYNAMIC coordinator prompt — reads candidate first, routes to partitions
# ---------------------------------------------------------------------------

DYNAMIC_COORDINATOR = """You are a job application screening coordinator.

You will receive a set of pre-planned screening PARTITIONS as JSON. Each partition defines
one agent's exclusive scope (topic, cover, exclude). Follow this workflow exactly:

PHASE 1 — SCREENING
1. Invoke exactly one screening_agent call per partition — no more, no less.
2. In each call set partition_agent to the partition's "agent" name.
3. Formulate the question so it stays strictly within that partition's "cover" list
   and never touches aspects listed in "exclude".

PHASE 2 — EVALUATE COVERAGE
4. After all partition agents have reported, call evaluate_coverage with a summary of
   all findings, a coverage score (1-10), any gaps you see, and whether coverage is sufficient.
5. If sufficient=false, call screening_agent for each gap to fill it (max 2 gap-filling rounds).
   Re-evaluate after each round.

PHASE 3 — FINAL RECOMMENDATION
6. Once coverage is sufficient, call submit_final with your verdict (HIRE/MAYBE/PASS),
   a rationale, key strengths, and key concerns.
   Do NOT end with a plain text message — submit_final is the only valid conclusion."""


async def run_coordinator(
    client, coordinator_prompt: str, label: str,
    job_posting: str, resume: str
) -> list[dict]:
    log.info("=" * 60)
    log.info(label)
    log.info("=" * 60)

    # Step 1 — generate non-overlapping partitions
    log.info("[PARTITION] Generating screening partitions...")
    partitions = await generate_partitions(client, job_posting, resume)
    log.info("[PARTITION] %d partitions generated:\n%s", len(partitions), json.dumps(partitions, indent=2))

    # Validate: no duplicate cover items across agents
    all_cover: list[str] = []
    for p in partitions:
        for item in p.get("scope", {}).get("cover", []):
            if item.lower() in [c.lower() for c in all_cover]:
                log.warning("[ERROR] Overlap detected: '%s' appears in multiple partitions", item)
            all_cover.append(item)

    # Build a partition lookup by agent name for context injection
    partition_by_name: dict[str, dict] = {p["agent"]: p for p in partitions}

    # Step 2 — pass partitions to the coordinator
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

    # Fix 3 — trace: stores every spoke interaction with full inputs and outputs
    trace: list[dict] = []
    final_verdict: dict | None = None
    step = 0

    try:
        while step < 30:
            step += 1
            response = await client.messages.create(
                model=model,
                max_tokens=2048,
                system=coordinator_prompt,
                tools=tools,
                messages=messages,
            )

            # Log any coordinator reasoning text
            for block in response.content:
                if hasattr(block, "text") and block.text.strip():
                    log.info("[COORDINATOR_TEXT] step=%d  %s", step, block.text.strip()[:300])

            if response.stop_reason == "end_turn":
                # Coordinator ended without calling submit_final — surface what it said
                final_text = next((b.text for b in response.content if hasattr(b, "text")), "")
                log.warning("[WARN] Coordinator ended via end_turn instead of submit_final.")
                if final_text:
                    log.info("[FINAL] (via end_turn)\n%s", final_text)
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    # --- screening_agent ---
                    if block.name == "screening_agent":
                        partition_agent = block.input.get("partition_agent", "unknown")
                        question = block.input["question"]
                        partition = partition_by_name.get(partition_agent)

                        log.info(
                            "[DELEGATE] step=%d  partition=%s  question=%s",
                            step, partition_agent, question
                        )

                        result = await call_screening_agent(
                            client, question, job_posting, resume, partition=partition
                        )

                        log.info(
                            "[SPOKE_RESULT] partition=%s  response=%s",
                            partition_agent, result[:200]
                        )

                        # Fix 3 — persist both input and output
                        trace.append({
                            "step": step,
                            "partition_agent": partition_agent,
                            "question": question,
                            "response": result,
                            "timestamp": _ts(),
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                    # Fix 4 — evaluate_coverage
                    elif block.name == "evaluate_coverage":
                        score = block.input.get("coverage_score", "?")
                        gaps = block.input.get("gaps", [])
                        sufficient = block.input.get("sufficient", False)
                        log.info(
                            "[COVERAGE] step=%d  score=%s/10  sufficient=%s  gaps=%s",
                            step, score, sufficient, gaps
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({
                                "coverage_score": score,
                                "gaps": gaps,
                                "sufficient": sufficient,
                            }),
                        })

                    # Fix 5 — submit_final exit gate
                    elif block.name == "submit_final":
                        final_verdict = {
                            "verdict":       block.input.get("verdict"),
                            "rationale":     block.input.get("rationale"),
                            "key_strengths": block.input.get("key_strengths", []),
                            "key_concerns":  block.input.get("key_concerns", []),
                        }
                        log.info(
                            "[FINAL] verdict=%s\n  rationale: %s\n  strengths: %s\n  concerns: %s",
                            final_verdict["verdict"],
                            final_verdict["rationale"],
                            final_verdict["key_strengths"],
                            final_verdict["key_concerns"],
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Recommendation submitted.",
                        })
                        # Exit after final is submitted
                        messages += [
                            {"role": "assistant", "content": response.content},
                            {"role": "user",      "content": tool_results},
                        ]
                        step = 999  # signal exit
                        break

                if step == 999:
                    break

                messages += [
                    {"role": "assistant", "content": response.content},
                    {"role": "user",      "content": tool_results},
                ]
        else:
            log.warning("[WARN] Reached step limit without submit_final.")

    except Exception as exc:
        log.error("[ERROR] Coordinator loop failed at step %d: %s", step, exc)
        raise

    return trace, final_verdict


# ---------------------------------------------------------------------------
# Fix 3 — print_trace: full execution trace dump
# ---------------------------------------------------------------------------

def print_trace(trace: list[dict]) -> None:
    log.info("=" * 60)
    log.info("EXECUTION TRACE  (%d spoke calls)", len(trace))
    log.info("=" * 60)
    for i, entry in enumerate(trace, 1):
        log.info(
            "  [%2d] ts=%s  partition=%-30s\n"
            "       Q: %s\n"
            "       A: %s",
            i,
            entry["timestamp"],
            entry["partition_agent"],
            entry["question"],
            entry["response"][:200],
        )


def coverage_report(trace: list[dict]) -> None:
    dynamic_qs = [e["question"] for e in trace]
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

    log.info("=" * 60)
    log.info("COVERAGE REPORT")
    log.info("=" * 60)
    log.info("  Dynamic coordinator:  %d screening angles", len(dynamic_qs))
    log.info("  %-45s %s", "Dimension", "Covered")
    log.info("  %s %s", "-" * 45, "-" * 8)

    for label, keywords in dimensions:
        mark = "YES" if covered(dynamic_qs, keywords) else " NO"
        log.info("  %-45s %s", label, mark)


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

        log.info("Candidate: Alex Chen — Senior Python Backend Engineer application")
        log.info("Coordinator: reads partitions, routes to spokes, evaluates coverage, submits final verdict.")

        trace, final_verdict = await run_coordinator(
            client, DYNAMIC_COORDINATOR,
            "COORDINATOR WITH OBSERVABILITY LAYER",
            job_posting, resume,
        )

        print_trace(trace)
        coverage_report(trace)

        if final_verdict:
            log.info("=" * 60)
            log.info("FINAL VERDICT: %s", final_verdict["verdict"])
            log.info("=" * 60)


asyncio.run(main())
