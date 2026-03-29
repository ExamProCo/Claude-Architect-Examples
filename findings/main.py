import json
import anyio
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from pydantic import BaseModel
from dotenv import load_dotenv

from claude_agent_sdk import (
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AgentDefinition,
    AssistantMessage,
    TextBlock,
    tool,
)

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Use case: Film Research — Find late-1970s / 1980s films similar to
# "School in the Crosshairs" (Nerawareta Gakuen, 1981, dir. Nobuhiko Obayashi)
# A Japanese sci-fi/fantasy film: psychic teen vs. mind-control cult at school.
# ---------------------------------------------------------------------------

model = "claude-haiku-4-5-20251001"
TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# Finding schema — Pydantic models (validated + serializable)
# ---------------------------------------------------------------------------

class FindingSource(BaseModel):
    type: Literal["agent_output"] = "agent_output"
    name: str                           # "Film Title (Year)"
    author: str = ""                    # director
    published_at: str = ""              # "YYYY-01-01"
    accessed_at: str = TODAY


class FindingItem(BaseModel):
    """Schema returned by the research sub-agent (no ID — assigned by coordinator)."""
    content: str
    confidence: Literal["high", "medium", "low"]
    type: Literal["claim", "summary"]
    source: FindingSource
    tags: list[str] = []


class FindingList(BaseModel):
    """Wrapper used as the sub-agent's structured output schema."""
    findings: list[FindingItem]


class Finding(FindingItem):
    """FindingItem + stable ID assigned by the coordinator."""
    id: str


# ---------------------------------------------------------------------------
# State — shared across all tool calls
# ---------------------------------------------------------------------------

@dataclass
class ResearchState:
    findings: list[Finding] = field(default_factory=list)
    _counter: list[int] = field(default_factory=lambda: [0])

    def next_id(self) -> str:
        self._counter[0] += 1
        return f"finding_{self._counter[0]:03d}"


# ---------------------------------------------------------------------------
# Research sub-agent — AgentDefinition (spawned by coordinator via Agent tool)
# ---------------------------------------------------------------------------

RESEARCH_AGENT = AgentDefinition(
    description="Researches late-1970s/1980s films similar to 'School in the Crosshairs' for a given similarity angle. Returns a JSON findings object.",
    prompt="""You are a specialist film researcher with deep knowledge of
late-1970s and 1980s cinema, particularly Japanese and international genre films.

You will be asked to research a specific angle of similarity to "School in the Crosshairs"
(Nerawareta Gakuen, 1981, dir. Nobuhiko Obayashi). That film features:
- Psychic / ESP powers (telekinesis, telepathy, precognition)
- A high school setting
- A cult / mind-control antagonist
- Teenage protagonist discovering her abilities
- Blends of coming-of-age drama, supernatural thriller, and sci-fi
- Stylised, visually inventive direction

Return your findings as a JSON object (no markdown fences, no commentary):
{
  "findings": [
    {
      "content": "one sentence describing the film and its similarity",
      "confidence": "high" | "medium" | "low",
      "type": "claim" | "summary",
      "source": {
        "type": "agent_output",
        "name": "Film Title (Year)",
        "author": "Director Full Name",
        "published_at": "YYYY-01-01"
      },
      "tags": ["tag1", "tag2"]
    }
  ]
}""",
    tools=[],
    model="haiku",
)


# ---------------------------------------------------------------------------
# MCP tools — bound to state via closure
# ---------------------------------------------------------------------------

def make_tools(state: ResearchState) -> list:

    @tool(
        "record_findings",
        "Validate and store the JSON output returned by a research_agent call. "
        "Pass the agent's exact output string — findings are parsed, validated, "
        "and assigned stable IDs.",
        {"agent_output": str},
    )
    async def mcp_record_findings(args: dict) -> dict:
        validated = FindingList.model_validate_json(args["agent_output"])
        added = []
        for item in validated.findings:
            f = Finding(id=state.next_id(), **item.model_dump())
            state.findings.append(f)
            added.append(f"[{f.id}] {f.source.name} — {f.content}")
            print(f"  [finding] {f.id}  {f.source.name}")
        return {"content": [{"type": "text", "text": f"Recorded {len(added)} findings."}]}

    @tool(
        "evaluate_coverage",
        "Assess whether findings adequately cover the similarity landscape. "
        "Provide your own coverage_score, gaps, and sufficient judgment — "
        "the tool logs and returns your assessment so you can decide next steps.",
        {"findings_summary": str, "coverage_score": int, "gaps": list, "sufficient": bool},
    )
    async def mcp_evaluate_coverage(args: dict) -> dict:
        score = args.get("coverage_score", "?")
        gaps = args.get("gaps", [])
        sufficient = args.get("sufficient", False)
        print(f"\n  [coverage] score={score}/10  sufficient={sufficient}")
        if gaps:
            print(f"  gaps: {', '.join(gaps)}")
        payload = json.dumps({"coverage_score": score, "gaps": gaps, "sufficient": sufficient})
        return {"content": [{"type": "text", "text": payload}]}

    @tool(
        "submit_complete",
        "Signal research is complete and provide a synthesis. "
        "Call only after evaluate_coverage confirms sufficient=true "
        "or the refinement limit is reached.",
        {"summary": str},
    )
    async def mcp_submit_complete(args: dict) -> dict:
        print(f"\n{'=' * 60}")
        print("RESEARCH COMPLETE")
        print(f"{'=' * 60}")
        print(f"\n{args['summary']}\n")
        return {"content": [{"type": "text", "text": "Research complete."}]}

    return [mcp_record_findings, mcp_evaluate_coverage, mcp_submit_complete]


# ---------------------------------------------------------------------------
# Coordinator prompt
# ---------------------------------------------------------------------------

COORDINATOR_PROMPT = """You are a film research coordinator. Find late-1970s and 1980s films
(any country) similar to "School in the Crosshairs" (Nerawareta Gakuen, 1981).

Similarity axes to cover:
- Japanese supernatural / psychic school films of the era
- International teen psychic / telekinetic films (e.g. Carrie lineage)
- Mind-control or cult antagonist films
- Coming-of-age + genre hybrid films
- Visually inventive directors working in similar territory

PHASE 1 — Research: For each distinct axis:
  a. Use the Agent tool to call research_agent with a focused question.
  b. Immediately call record_findings with the agent's exact JSON output.

PHASE 2 — Evaluate: Call evaluate_coverage with a plain-text summary and your own assessment
           (score 0-10, gaps list, sufficient bool).
PHASE 3 — Fill gaps (max 2 rounds): If sufficient=false, spawn more research_agent calls,
           record their output, then re-evaluate.
PHASE 4 — Complete: Call submit_complete with a synthesis paragraph."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run(state: ResearchState) -> None:
    print("\n" + "=" * 60)
    print("FILM RESEARCH: Similar to 'School in the Crosshairs' (1981)")
    print("=" * 60 + "\n")

    server = create_sdk_mcp_server("research-tools", tools=make_tools(state))

    options = ClaudeAgentOptions(
        system_prompt=COORDINATOR_PROMPT,
        model=model,
        max_turns=30,
        allowed_tools=["Agent"],
        agents={"research_agent": RESEARCH_AGENT},
        mcp_servers={"research": server},
        permission_mode="bypassPermissions",
    )

    async with ClaudeSDKClient(options=options) as sdk_client:
        await sdk_client.query(
            "Find late-1970s and 1980s films similar to 'School in the Crosshairs' (1981). "
            "Cover all major similarity axes, evaluate coverage, then submit complete."
        )
        async for message in sdk_client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        print(f"[coordinator] {block.text.strip()}")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_findings(findings: list[Finding]) -> None:
    print(f"\n{'=' * 60}")
    print(f"FINDINGS  ({len(findings)} total)")
    print(f"{'=' * 60}\n")

    by_confidence: dict[str, list[Finding]] = {"high": [], "medium": [], "low": []}
    for f in findings:
        by_confidence.setdefault(f.confidence, []).append(f)

    for level in ("high", "medium", "low"):
        group = by_confidence.get(level, [])
        if not group:
            continue
        print(f"── {level.upper()} CONFIDENCE ({len(group)}) ──────────────────────\n")
        for f in group:
            print(f"  [{f.id}]  {f.source.name}  (dir. {f.source.author})")
            print(f"  {f.content}")
            if f.tags:
                print(f"  tags: {', '.join(f.tags)}")
            print()


def save_findings(findings: list[Finding], path: Path) -> None:
    path.write_text(json.dumps([f.model_dump() for f in findings], indent=2, ensure_ascii=False))
    print(f"Saved → {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    state = ResearchState()
    await run(state)
    print_findings(state.findings)
    save_findings(state.findings, Path(__file__).parent / "results.json")


anyio.run(main)
