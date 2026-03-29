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
    """The research document being cited — not the film itself."""
    type: Literal["agent_output"] = "agent_output"
    document: str = ""          # name of source (e.g. "IMDb", "Wikipedia", "Midnight Eye")
    url: str = ""               # URL to the source document
    excerpt: str = ""           # exact passage/text from the source that supports this finding
    published_at: str = ""      # when the source was published
    accessed_at: str = TODAY
    page: str = ""              # page or section if from a book/article


class FindingItem(BaseModel):
    """Schema returned by the research sub-agent (no ID — assigned by coordinator)."""
    film: str                   # "Film Title (Year)"
    director: str = ""          # director's full name
    content: str                # specific claim about why this film is similar
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

Each finding is one piece of evidence for why a specific film is similar.
The source is the research document you are citing, not the film itself.
The excerpt is the actual passage or text from that document that supports your claim —
quote it directly if possible, or paraphrase the key sentence if quoting is not possible.

Return your findings as a JSON object (no markdown fences, no commentary):
{
  "findings": [
    {
      "film": "Film Title (Year)",
      "director": "Director Full Name",
      "content": "one specific sentence about this film's similarity to School in the Crosshairs",
      "confidence": "high" | "medium" | "low",
      "type": "claim" | "summary",
      "source": {
        "type": "agent_output",
        "document": "name of the source (e.g. 'IMDb', 'Wikipedia', 'Midnight Eye', 'Senses of Cinema')",
        "url": "https://www.imdb.com/title/ttXXXXXXX/ or Wikipedia URL or other authoritative source",
        "excerpt": "the exact passage or key sentence from the source that supports this claim",
        "published_at": "YYYY-01-01",
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
      "film": "Film Title (Year)",
      "director": "Director Full Name",
      "content": "...",
      "confidence": "high" | "medium" | "low",
      "type": "claim" | "summary",
      "source": {
        "type": "agent_output",
        "document": "name of database, book, or article",
        "url": "best available source URL from the merged duplicates",
        "excerpt": "best available excerpt from the merged duplicates",
        "published_at": "YYYY-01-01",
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

def make_tools(state: ResearchState, logger: RunLogger, findings_path: Path) -> list:

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
                        title = film.get("title", film.get("film", film.get("name", "Unknown")))
                        year = film.get("year", "")
                        film_label = f"{title} ({year})" if year else title
                        findings_list.append(FindingItem(
                            film=film_label,
                            director=film.get("director", film.get("author", "")),
                            content=film.get("similarity_notes", film.get("content", f"{title} is similar to School in the Crosshairs")),
                            confidence="medium",
                            type="claim",
                            source=FindingSource(
                                document=film.get("document", ""),
                                url=film.get("url", ""),
                                excerpt=film.get("excerpt", ""),
                                published_at=f"{year}-01-01" if year else "",
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

            # Score against quality criteria so the coordinator gets immediate feedback.
            missing = []
            warnings = []
            if not f.director:
                missing.append("director")
            if not f.source.url:
                missing.append("source.url")
            if not f.source.excerpt:
                missing.append("source.excerpt")
            if not f.source.document:
                missing.append("source.document")
            if len(f.tags) < 2:
                missing.append(f"tags ({len(f.tags)} of 2 required)")

            # IMDb-only sourcing can verify a film exists but cannot justify a similarity
            # claim — the excerpt will just be a plot synopsis with no critical context.
            doc = (f.source.document or "").strip().lower()
            WEAK_SOURCES = {"imdb", "the internet movie database"}
            if doc in WEAK_SOURCES:
                warnings.append(
                    "source.document=IMDb only — IMDb confirms the film exists but does not "
                    "support a similarity claim; prefer a review, essay, or critical database "
                    "(e.g. Midnight Eye, Senses of Cinema, Letterboxd, BFI, Criterion)"
                )

            quality = "HIGH" if not missing else ("MEDIUM" if len(missing) == 1 else "LOW")
            parts = [f"quality={quality}"]
            if missing:
                parts.append(f"missing=[{', '.join(missing)}]")
            if warnings:
                parts.append(f"warn=[{'; '.join(warnings)}]")
            quality_note = " ".join(parts)
            added.append(f"[{f.id}] {f.film} — {quality_note}")
            logger.write("coordinator", f"  [finding] {f.id}  {f.film}  {quality_note}")

        # Source diversity across all stored findings.
        all_docs = [
            (f.source.document or "unknown").strip().lower()
            for f in state.findings
        ]
        doc_counts: dict[str, int] = {}
        for d in all_docs:
            doc_counts[d] = doc_counts.get(d, 0) + 1
        total_stored = len(state.findings)
        dominant = max(doc_counts, key=lambda k: doc_counts[k]) if doc_counts else ""
        dominant_pct = round(100 * doc_counts.get(dominant, 0) / total_stored) if total_stored else 0
        diversity_note = (
            f"source diversity: {len(doc_counts)} distinct source(s) across {total_stored} findings"
        )
        if dominant_pct >= 60:
            diversity_note += (
                f" — WARNING: '{dominant}' accounts for {dominant_pct}% of findings; "
                "seek more varied sources (reviews, critical essays, curated databases)"
            )

        # Persist incrementally so findings survive a crash or early exit.
        findings_path.write_text(
            json.dumps([f.model_dump() for f in state.findings], indent=2, ensure_ascii=False)
        )

        summary_lines = "\n".join(added)
        high = sum(1 for line in added if "quality=HIGH" in line)
        medium = sum(1 for line in added if "quality=MEDIUM" in line)
        low = sum(1 for line in added if "quality=LOW" in line)
        feedback = (
            f"Recorded {len(added)} findings (HIGH={high} MEDIUM={medium} LOW={low}). "
            f"Total stored: {total_stored}. {diversity_note}.\n{summary_lines}"
        )
        return {"content": [{"type": "text", "text": feedback}]}

    @tool(
        "evaluate_coverage",
        "Assess coverage using the quality feedback already returned by record_findings. "
        "Score 0-10 against ALL of: "
        "(1) at least 15 distinct films stored; "
        "(2) all five axes (A–E) covered by ≥2 HIGH/MEDIUM findings each — LOW findings do not count; "
        "(3) source diversity — findings must draw from ≥3 distinct source types; "
        "IMDb-only findings do not count toward axis coverage because IMDb confirms existence "
        "but cannot justify a similarity claim; critical sources (reviews, essays, curated databases) "
        "are required for HIGH quality. "
        "Set sufficient=true only when coverage_score >= 7, all axes are covered, "
        "and no single source accounts for ≥60% of findings. "
        "In gaps, name under-represented axes, over-dominant sources, and fields most often missing.",
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

GOAL:
  Produce a curated, source-backed list of at least 15 distinct films that a fan of
  "School in the Crosshairs" could watch next. The final output must cover all five
  similarity axes and include a ranked top-10 with a written synthesis.

QUALITY CRITERIA (apply at every phase):
  A finding is HIGH quality when ALL of the following hold:
    - film: "Title (Year)" with a real year
    - director: full name (not empty)
    - content: one specific, informative sentence about the film AND its similarity
    - confidence: "high" (film is verifiable and similarity is clear)
    - source.document: names the database or publication — must be a critical or curatorial
      source (e.g. "Midnight Eye", "Senses of Cinema", "BFI", "Criterion", "Letterboxd",
      "Wikipedia", a book or journal); IMDb alone is NOT sufficient because it only confirms
      a film exists — it cannot justify a similarity claim
    - source.url: a real authoritative URL (not empty)
    - source.excerpt: actual passage or key sentence from the source (not empty)
    - tags: at least 2 relevant thematic tags

  A finding is MEDIUM quality when it is verifiable but missing one of the above fields.
  A finding is LOW quality when the film or director cannot be verified, the similarity is
  vague, or the only source is IMDb.

  Coverage is SUFFICIENT when:
    - At least 15 distinct films have been recorded
    - All five axes (A–E) are represented by at least 2 HIGH/MEDIUM findings each
    - Findings draw from at least 3 distinct source types (not IMDb-dominant)
    - coverage_score >= 7

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

    findings_path = Path(__file__).parent / "results.json"
    server = create_sdk_mcp_server("research-tools", tools=make_tools(state, logger, findings_path))

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
            print(f"  [{f.id}]  {f.film}  (dir. {f.director})")
            print(f"  {f.content}")
            if f.source.excerpt:
                print(f"  excerpt:  \"{f.source.excerpt}\"")
            if f.source.document or f.source.url:
                doc_ref = f.source.document
                if f.source.page:
                    doc_ref += f", p.{f.source.page}"
                if f.source.url:
                    doc_ref += f"  <{f.source.url}>"
                print(f"  source:   {doc_ref}")
            if f.tags:
                print(f"  tags:     {', '.join(f.tags)}")
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
