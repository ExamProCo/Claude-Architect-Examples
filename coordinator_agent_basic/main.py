import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Use case: Job Application Screener — Hub & Spoke Architecture
#
# Hub (coordinator): owns routing decisions and result aggregation
# Spokes:            independent Claude agents, each with a single responsibility
#   - keyword_scanner:   fast presence/absence check for required skills
#   - deep_evaluator:    assesses experience depth and seniority fit
#   - red_flag_detector: identifies disqualifying signals
#   - score_aggregator:  combines all spoke outputs into a final decision
# ---------------------------------------------------------------------------

model = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Spoke system prompts
# ---------------------------------------------------------------------------

KEYWORD_SCANNER_PROMPT = """You are a resume keyword scanner. Check whether required skills
from the job posting appear explicitly in the resume.

For each required skill output one line:
  FOUND: <skill>
  MISSING: <skill>

Be literal. Do not infer or extrapolate. Report only what is explicitly stated."""

DEEP_EVALUATOR_PROMPT = """You are a senior technical recruiter evaluating depth of experience.

Assess whether the candidate's background genuinely matches the role's seniority and scope.
Consider: years of experience, project scale, leadership signals, recency of skills.

Write a short assessment paragraph, then end with exactly one of:
  VERDICT: Strong Fit
  VERDICT: Partial Fit
  VERDICT: Weak Fit"""

RED_FLAG_DETECTOR_PROMPT = """You are a resume red flag detector. Identify disqualifying signals only.

Look for: unexplained employment gaps over 6 months, frequent job hopping (under 1 year at
multiple consecutive roles), clear seniority mismatch, or missing hard requirements.

Output each finding as:
  RED FLAG: <description>

If nothing disqualifying is found, output only:
  NO RED FLAGS"""

SCORE_AGGREGATOR_PROMPT = """You are a hiring decision aggregator. You receive outputs from three
independent screening agents and produce a single structured recommendation.

Output exactly in this format:
  KEYWORD MATCH: <X of Y required skills found>
  EXPERIENCE FIT: <Strong / Partial / Weak>
  RED FLAGS: <None, or a brief summary>
  DECISION: <HIRE / MAYBE / PASS>
  REASON: <one sentence justification>"""

# ---------------------------------------------------------------------------
# Spoke agents — each is an independent Claude API call
# ---------------------------------------------------------------------------

async def spoke_keyword_scanner(client, job_posting: str, resume: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=KEYWORD_SCANNER_PROMPT,
        messages=[{"role": "user", "content": f"JOB POSTING:\n{job_posting}\n\nRESUME:\n{resume}"}],
    )
    return response.content[0].text


async def spoke_deep_evaluator(client, job_posting: str, resume: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=DEEP_EVALUATOR_PROMPT,
        messages=[{"role": "user", "content": f"JOB POSTING:\n{job_posting}\n\nRESUME:\n{resume}"}],
    )
    return response.content[0].text


async def spoke_red_flag_detector(client, job_posting: str, resume: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=RED_FLAG_DETECTOR_PROMPT,
        messages=[{"role": "user", "content": f"JOB POSTING:\n{job_posting}\n\nRESUME:\n{resume}"}],
    )
    return response.content[0].text


async def spoke_score_aggregator(client, keyword_result: str, deep_result: str, red_flag_result: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=SCORE_AGGREGATOR_PROMPT,
        messages=[{"role": "user", "content": (
            f"Keyword Scanner:\n{keyword_result}\n\n"
            f"Deep Evaluator:\n{deep_result}\n\n"
            f"Red Flag Detector:\n{red_flag_result}"
        )}],
    )
    return response.content[0].text

# ---------------------------------------------------------------------------
# Async tool dispatcher — coordinator calls spokes through here
# ---------------------------------------------------------------------------

async def dispatch_tool(client, name: str, inputs: dict) -> str:
    if name == "run_keyword_scanner":
        return await spoke_keyword_scanner(client, **inputs)
    if name == "run_deep_evaluator":
        return await spoke_deep_evaluator(client, **inputs)
    if name == "run_red_flag_detector":
        return await spoke_red_flag_detector(client, **inputs)
    if name == "run_score_aggregator":
        return await spoke_score_aggregator(client, **inputs)
    return f"Unknown tool: {name}"

# ---------------------------------------------------------------------------
# Tool schemas — what the coordinator hub sees
# ---------------------------------------------------------------------------

JOB_RESUME_PROPERTIES = {
    "job_posting": {"type": "string", "description": "The full job posting text"},
    "resume":      {"type": "string", "description": "The full resume text"},
}

tools = [
    {
        "name": "run_keyword_scanner",
        "description": (
            "Spoke agent: scans the resume for presence or absence of each required skill "
            "listed in the job posting. Fast, literal check — no inference."
        ),
        "input_schema": {
            "type": "object",
            "properties": JOB_RESUME_PROPERTIES,
            "required": ["job_posting", "resume"],
        },
    },
    {
        "name": "run_deep_evaluator",
        "description": (
            "Spoke agent: assesses whether the candidate's experience depth and seniority "
            "genuinely matches the role. Returns a verdict of Strong / Partial / Weak Fit."
        ),
        "input_schema": {
            "type": "object",
            "properties": JOB_RESUME_PROPERTIES,
            "required": ["job_posting", "resume"],
        },
    },
    {
        "name": "run_red_flag_detector",
        "description": (
            "Spoke agent: identifies disqualifying signals such as employment gaps, "
            "job hopping, or missing hard requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": JOB_RESUME_PROPERTIES,
            "required": ["job_posting", "resume"],
        },
    },
    {
        "name": "run_score_aggregator",
        "description": (
            "Spoke agent: takes outputs from the three screening agents and produces "
            "a final structured HIRE / MAYBE / PASS recommendation. "
            "Call this only after all three screening agents have returned results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword_result":   {"type": "string", "description": "Output from run_keyword_scanner"},
                "deep_result":      {"type": "string", "description": "Output from run_deep_evaluator"},
                "red_flag_result":  {"type": "string", "description": "Output from run_red_flag_detector"},
            },
            "required": ["keyword_result", "deep_result", "red_flag_result"],
        },
    },
]

# ---------------------------------------------------------------------------
# Coordinator (hub) system prompt
# ---------------------------------------------------------------------------

COORDINATOR_PROMPT = """You are a job application screening coordinator.

Your job is to orchestrate three independent screening agents and then aggregate their results.

Steps:
1. Run all three screening agents — keyword_scanner, deep_evaluator, red_flag_detector —
   passing the full job_posting and resume text to each.
2. Once all three have returned results, pass their outputs to run_score_aggregator.
3. Present the final recommendation to the user.

You may run the three screening agents in any order. Do not skip any of them."""

# ---------------------------------------------------------------------------
# Coordinator agentic loop
# ---------------------------------------------------------------------------

async def create(client, messages):
    return await client.messages.create(
        model=model,
        max_tokens=2048,
        system=COORDINATOR_PROMPT,
        tools=tools,
        messages=messages,
    )


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

        user_message = (
            f"Please screen this application.\n\n"
            f"JOB POSTING:\n{job_posting}\n\n"
            f"RESUME:\n{resume}"
        )

        print(f"User: Screen application for Senior Python Backend Engineer\n")
        messages = [{"role": "user", "content": user_message}]

        # --- Coordinator agentic loop ---
        # 4 spokes + 1 final end_turn = 5 expected steps; cap at 10 as a safety net
        MAX_STEPS = 10
        step = 0
        while step < MAX_STEPS:
            step += 1
            response = await create(client, messages)
            print(f"[Step {step}/{MAX_STEPS}] stop_reason={response.stop_reason}")

            if response.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    "(no text)"
                )
                print(f"\nCoordinator: {final_text}")
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"  → Coordinator routes to spoke: {block.name}")
                        result = await dispatch_tool(client, block.name, block.input)
                        print(f"    Spoke result:\n{result}\n")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages += [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ]

        else:
            print(f"\n[WARN] Reached max steps ({MAX_STEPS}) without end_turn — aborting loop.")

asyncio.run(main())
