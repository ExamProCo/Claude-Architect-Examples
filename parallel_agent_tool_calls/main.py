import json
import anyio
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime
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
    ToolUseBlock,
    ToolResultBlock,
    tool,
)

load_dotenv(Path(__file__).parent.parent / ".env")


# ---------------------------------------------------------------------------
# Run logger — writes coordinator + per-agent logs to logs/run-<timestamp>/
# ---------------------------------------------------------------------------

class RunLogger:
    def __init__(self, base_dir: Path):
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        self.run_dir = base_dir / f"run-{ts}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, object] = {}

    def _fh(self, channel: str):
        if channel not in self._handles:
            fh = open(self.run_dir / f"{channel}.log", "w", buffering=1, encoding="utf-8")
            self._handles[channel] = fh
        return self._handles[channel]

    def write(self, channel: str, msg: str, *, echo: bool = True) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}\n"
        if echo:
            print(msg)
        fh = self._fh(channel)
        fh.write(line)

    def close(self) -> None:
        for fh in self._handles.values():
            fh.close()


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
    url: str = ""                       # source URL (IMDb, Wikipedia, archive, etc.)
    document: str = ""                  # book/article/database name
    page: str = ""                      # page number or section if applicable


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
        "published_at": "YYYY-01-01",
        "url": "https://www.imdb.com/title/ttXXXXXXX/ or Wikipedia URL or other authoritative source",
        "document": "name of database, book, or article this came from (e.g. 'IMDb', 'Wikipedia', 'Midnight Eye')",
        "page": "page number or section if from a book/article, otherwise empty string"
      },
      "tags": ["tag1", "tag2"]
    }
  ]
}""",
    tools=[],
    model="haiku",
)

DEDUP_AGENT = AgentDefinition(
    description="Deduplicates a combined list of film findings, merging near-identical entries. Returns a clean JSON findings object.",
    prompt="""You are a film research editor. You will receive a JSON array of findings
about films similar to "School in the Crosshairs" (1981), gathered from multiple
research passes. Your job is to deduplicate them.

Rules:
- If the same film appears more than once, keep the single best entry:
  prefer higher confidence, then richer content, then more tags.
- Merge tags from duplicate entries into the surviving entry.
- Do NOT drop films just because they are similar to each other — only remove
  true duplicates (same film title and year).
- Preserve all unique films.

Return a clean JSON object (no markdown fences, no commentary):
{
  "findings": [
    {
      "content": "...",
      "confidence": "high" | "medium" | "low",
      "type": "claim" | "summary",
      "source": {
        "type": "agent_output",
        "name": "Film Title (Year)",
        "author": "Director Full Name",
        "published_at": "YYYY-01-01",
        "url": "best available source URL from the merged duplicates",
        "document": "name of database, book, or article",
        "page": "page number or section if applicable, otherwise empty string"
      },
      "tags": ["tag1", "tag2"]
    }
  ]
}""",
    tools=[],
    model="haiku",
)

RANK_AGENT = AgentDefinition(
    description="Ranks deduplicated film findings by overall similarity to 'School in the Crosshairs', returning a top-10 ordered summary.",
    prompt="""You are a film critic and curator specialising in late-1970s/1980s genre cinema.
You will receive a JSON array of deduplicated findings about films similar to
"School in the Crosshairs" (Nerawareta Gakuen, 1981, dir. Nobuhiko Obayashi).

Score each film holistically across these dimensions:
1. Thematic overlap (psychic powers, school setting, cult/mind-control)
2. Tonal match (coming-of-age + genre hybrid, stylised direction)
3. Era match (1975–1989 preferred)
4. Confidence of the finding

Return a JSON object with the top 10 films ranked from most to least similar
(no markdown fences, no commentary):
{
  "ranked": [
    {
      "rank": 1,
      "name": "Film Title (Year)",
      "director": "Director Full Name",
      "reason": "one sentence explaining why this ranks here"
    }
  ],
  "synthesis": "two-to-three sentence paragraph summarising the landscape of similar films"
}""",
    tools=[],
    model="haiku",
)


# ---------------------------------------------------------------------------
# MCP tools — bound to state via closure
# ---------------------------------------------------------------------------

def make_tools(state: ResearchState, logger: RunLogger) -> list:

    @tool(
        "record_findings",
        "Validate and store the JSON output returned by a research_agent call. "
        "Pass the agent's exact output string — findings are parsed, validated, "
        "and assigned stable IDs. Accepts either the full FindingList object "
        '{"findings": [...]} or a plain JSON array of film objects.',
        {"agent_output": str},
    )
    async def mcp_record_findings(args: dict) -> dict:
        raw = args["agent_output"]
        try:
            validated = FindingList.model_validate_json(raw)
        except Exception as primary_err:
            logger.write("coordinator", f"  [record_findings:warn] Primary parse failed: {primary_err}")
            logger.write("coordinator", f"  [record_findings:input] {raw[:300]}", echo=False)
            # Fallback: coordinator often returns a plain list of film dicts.
            try:
                items = json.loads(raw)
                if isinstance(items, list):
                    findings_list = []
                    for film in items:
                        title = film.get("title", film.get("name", "Unknown"))
                        year = film.get("year", "")
                        name = f"{title} ({year})" if year else title
                        findings_list.append(FindingItem(
                            content=film.get("similarity_notes", film.get("content", f"{title} is similar to School in the Crosshairs")),
                            confidence="medium",
                            type="claim",
                            source=FindingSource(
                                name=name,
                                author=film.get("director", film.get("author", "")),
                                published_at=f"{year}-01-01" if year else "",
                                url=film.get("url", ""),
                                document=film.get("document", ""),
                            ),
                            tags=film.get("key_themes", film.get("tags", [])),
                        ))
                    validated = FindingList(findings=findings_list)
                    logger.write("coordinator", f"  [record_findings:info] Converted {len(findings_list)} plain film objects")
                else:
                    raise ValueError(f"Expected list or FindingList object, got {type(items)}")
            except Exception as fallback_err:
                logger.write("coordinator", f"  [record_findings:error] Fallback also failed: {fallback_err}")
                return {"content": [{"type": "text", "text": f"ERROR: Could not parse findings. Primary: {primary_err}. Fallback: {fallback_err}. Input preview: {raw[:200]}"}], "isError": True}

        added = []
        for item in validated.findings:
            f = Finding(id=state.next_id(), **item.model_dump())
            state.findings.append(f)
            added.append(f"[{f.id}] {f.source.name} — {f.content}")
            logger.write("coordinator", f"  [finding] {f.id}  {f.source.name}")
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
        logger.write("coordinator", f"\n  [coverage] score={score}/10  sufficient={sufficient}")
        if gaps:
            logger.write("coordinator", f"  gaps: {', '.join(gaps)}")
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
        logger.write("coordinator", f"\n{'=' * 60}")
        logger.write("coordinator", "RESEARCH COMPLETE")
        logger.write("coordinator", f"{'=' * 60}")
        logger.write("coordinator", f"\n{args['summary']}\n")
        return {"content": [{"type": "text", "text": "Research complete."}]}

    return [mcp_record_findings, mcp_evaluate_coverage, mcp_submit_complete]


# ---------------------------------------------------------------------------
# Coordinator prompt
# ---------------------------------------------------------------------------

COORDINATOR_PROMPT = """You are a film research coordinator. Find late-1970s and 1980s films
(any country) similar to "School in the Crosshairs" (Nerawareta Gakuen, 1981).

PHASE 1 — Parallel Research:
  In a SINGLE response, call research_agent simultaneously for ALL FIVE axes at once
  (do not wait between calls — all five Agent tool calls must appear in the same turn):
    Axis A: Japanese supernatural/psychic school films (1975–1989)
    Axis B: International teen psychic/telekinetic films — the Carrie lineage
    Axis C: Mind-control or cult-antagonist films (any country, 1975–1989)
    Axis D: Coming-of-age + genre hybrid films (horror, sci-fi, or fantasy blend)
    Axis E: Visually inventive auteur directors working in similar stylised territory

PHASE 2 — Record:
  Call record_findings for each of the 5 agent outputs.
  These can also be batched in parallel (all five in one turn).

PHASE 3 — Deduplicate:
  Call dedup_agent, passing ALL current findings as a single JSON array string.
  Then call record_findings with its output to replace the raw set.

PHASE 4 — Evaluate:
  Call evaluate_coverage with a plain-text summary and your own assessment
  (score 0-10, gaps list, sufficient bool).
  If sufficient=false (max 2 rounds), spawn gap-filling research_agent calls
  in parallel, record them, then re-evaluate.

PHASE 5 — Rank:
  Call rank_agent, passing the final deduplicated findings as a JSON array string.

PHASE 6 — Complete:
  Call submit_complete with the ranked synthesis returned by rank_agent."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run(state: ResearchState) -> None:
    logs_dir = Path(__file__).parent / "logs"
    logger = RunLogger(logs_dir)
    print(f"\nLogs → {logger.run_dir}\n")

    logger.write("coordinator", "=" * 60)
    logger.write("coordinator", "FILM RESEARCH: Similar to 'School in the Crosshairs' (1981)")
    logger.write("coordinator", "=" * 60)

    server = create_sdk_mcp_server("research-tools", tools=make_tools(state, logger))

    options = ClaudeAgentOptions(
        system_prompt=COORDINATOR_PROMPT,
        model=model,
        max_turns=30,
        allowed_tools=["Agent"],
        agents={
            "research_agent": RESEARCH_AGENT,
            "dedup_agent": DEDUP_AGENT,
            "rank_agent": RANK_AGENT,
        },
        mcp_servers={"research": server},
        permission_mode="bypassPermissions",
    )

    # Maps tool_use_id → agent log channel name so results land in the right file.
    agent_calls: dict[str, str] = {}
    agent_call_counts: dict[str, int] = {}

    try:
        async with ClaudeSDKClient(options=options) as sdk_client:
            await sdk_client.query(
                "Find late-1970s and 1980s films similar to 'School in the Crosshairs' (1981). "
                "Cover all major similarity axes, evaluate coverage, then submit complete."
            )
            async for message in sdk_client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            logger.write("coordinator", f"[coordinator] {block.text.strip()}")

                        elif isinstance(block, ToolUseBlock):
                            if block.name == "Agent":
                                agent_type = block.input.get("agent", "agent")
                                n = agent_call_counts.get(agent_type, 0) + 1
                                agent_call_counts[agent_type] = n
                                # Use a unique channel per call so concurrent agents don't mix.
                                channel = agent_type if n == 1 else f"{agent_type}_{n}"
                                agent_calls[block.id] = channel

                                prompt = block.input.get("prompt", "")
                                desc = prompt[:80].replace("\n", " ")
                                logger.write("coordinator", f"  [agent:start] {channel} — {desc}")
                                logger.write(channel, f"=== AGENT: {channel} ===")
                                logger.write(channel, f"PROMPT:\n{prompt}", echo=False)
                            else:
                                logger.write("coordinator", f"  [tool:call]   {block.name}")

                        elif isinstance(block, ToolResultBlock):
                            tid = getattr(block, "tool_use_id", getattr(block, "id", "?"))
                            status = "ok" if not getattr(block, "is_error", False) else "error"
                            logger.write("coordinator", f"  [tool:result] id={tid} status={status}")

                            # Write agent output to its dedicated log file.
                            if tid in agent_calls:
                                channel = agent_calls[tid]
                                raw = ""
                                content = getattr(block, "content", None)
                                if isinstance(content, str):
                                    raw = content
                                elif isinstance(content, list):
                                    parts = []
                                    for c in content:
                                        if isinstance(c, dict):
                                            parts.append(c.get("text", ""))
                                        elif hasattr(c, "text"):
                                            parts.append(c.text)
                                    raw = "\n".join(parts)
                                logger.write(channel, f"STATUS: {status}", echo=False)
                                logger.write(channel, f"OUTPUT:\n{raw}", echo=False)
                                logger.write("coordinator", f"  [agent:done]  {channel}")
    finally:
        logger.close()


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
            if f.source.url:
                print(f"  url:      {f.source.url}")
            if f.source.document:
                doc_ref = f.source.document
                if f.source.page:
                    doc_ref += f", p.{f.source.page}"
                print(f"  source:   {doc_ref}")
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
