import json
import anyio
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from claude_agent_sdk import (
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    TaskStartedMessage,
    TaskProgressMessage,
    ResultMessage,
    SystemMessage,
    tool,
)

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Use case: Film Research — Find late-1970s / 1980s films similar to
# "School in the Crosshairs" (Nerawareta Gakuen, 1981, dir. Nobuhiko Obayashi)
# ---------------------------------------------------------------------------

model = "claude-haiku-4-5-20251001"
ROOT = Path(__file__).parent
MANIFEST_PATH = ROOT / "manifest.json"
FINDINGS_DIR = ROOT / "FINDINGS"
SYNTHESIS_DIR = FINDINGS_DIR / "_synthesis"


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"version": 1, "tasks": []}


def save_manifest(m: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(m, indent=2) + "\n")


def alloc_task(kind: str, question: str, inputs: list[str] | None = None) -> str:
    m = load_manifest()
    next_num = len(m["tasks"]) + 1
    task_id = f"t-{next_num:04d}"
    m["tasks"].append({
        "id": task_id,
        "kind": kind,
        "question": question,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "artifact": None,
        "inputs": inputs or [],
        "notes": "",
    })
    save_manifest(m)
    return task_id


def mark_task_running(task_id: str) -> None:
    m = load_manifest()
    for t in m["tasks"]:
        if t["id"] == task_id:
            t["status"] = "running"
            t["started_at"] = now_iso()
    save_manifest(m)


def get_complete_artifacts() -> list[str]:
    m = load_manifest()
    return [
        t["artifact"] for t in m["tasks"]
        if t["kind"] == "explore" and t["status"] == "complete" and t["artifact"]
    ]


def resume_tasks() -> list[dict]:
    m = load_manifest()
    return [t for t in m["tasks"] if t["status"] in ("running", "failed") and t["kind"] == "explore"]


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def make_tools() -> list:

    @tool(
        "evaluate_coverage",
        "Assess whether scratchpads adequately cover the similarity landscape. "
        "Provide coverage_score (0-10), gaps list, and sufficient bool.",
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
        "Signal research is complete. Call with the path to the synthesis doc.",
        {"synthesis_path": str, "summary": str},
    )
    async def mcp_submit_complete(args: dict) -> dict:
        print(f"\n{'=' * 60}")
        print("RESEARCH COMPLETE")
        print(f"{'=' * 60}")
        print(f"\nSynthesis doc: {args.get('synthesis_path', '(none)')}")
        print(f"\n{args['summary']}\n")
        return {"content": [{"type": "text", "text": "Research complete."}]}

    @tool(
        "alloc_and_mark_running",
        "Allocate a new manifest task row and mark it running. Returns the task_id.",
        {"kind": str, "question": str, "inputs": list},
    )
    async def mcp_alloc_and_mark_running(args: dict) -> dict:
        task_id = alloc_task(args["kind"], args["question"], args.get("inputs", []))
        mark_task_running(task_id)
        return {"content": [{"type": "text", "text": task_id}]}

    @tool(
        "get_complete_scratchpads",
        "Return list of artifact paths for all completed explore tasks.",
        {},
    )
    async def mcp_get_complete_scratchpads(args: dict) -> dict:
        paths = get_complete_artifacts()
        return {"content": [{"type": "text", "text": json.dumps(paths)}]}

    return [
        mcp_evaluate_coverage,
        mcp_submit_complete,
        mcp_alloc_and_mark_running,
        mcp_get_complete_scratchpads,
    ]


# ---------------------------------------------------------------------------
# Coordinator prompt
# ---------------------------------------------------------------------------

def build_coordinator_prompt() -> str:
    stale = resume_tasks()
    resume_section = ""
    if stale:
        lines = "\n".join(
            f"  - task_id={t['id']}  status={t['status']}  resume_from={t.get('artifact') or '(none)'}  question={t['question']}"
            for t in stale
        )
        resume_section = (
            f"\nRe-dispatch these interrupted tasks first. "
            f"When dispatching, include `resume_from: <artifact path>` in the subagent prompt "
            f"if the artifact is not '(none)' — the explorer will read the partial scratchpad "
            f"and only research the remaining films needed to reach 4 findings:\n{lines}\n"
        )

    return f"""You are a film research coordinator. Find late-1970s and 1980s films similar to
"School in the Crosshairs" (Nerawareta Gakuen, 1981, dir. Nobuhiko Obayashi).
{resume_section}
Axis to cover (ONE only, for source provenance testing):
- Japanese supernatural / psychic school films of the era

Phase 1 — Call alloc_and_mark_running for the axis, then dispatch movie-explorer with the returned task_id. Wait for it to finish.
Phase 2 — Call evaluate_coverage from the explorer summary only (never open scratchpads yourself).
Phase 3 — Call get_complete_scratchpads, alloc_and_mark_running for synthesis, then dispatch movie-synthesizer.
Phase 4 — Call submit_complete with the synthesis path.

FINDINGS/ → {FINDINGS_DIR}  |  manifest → {MANIFEST_PATH}
"""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run() -> None:
    print("\n" + "=" * 60)
    print("FILM RESEARCH: Similar to 'School in the Crosshairs' (1981)")
    print("=" * 60 + "\n")

    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)

    server = create_sdk_mcp_server("research-tools", tools=make_tools())

    options = ClaudeAgentOptions(
        system_prompt=build_coordinator_prompt(),
        model=model,
        max_turns=40,
        allowed_tools=["Agent"],
        mcp_servers={"research": server},
        permission_mode="bypassPermissions",
    )

    async with ClaudeSDKClient(options=options) as sdk_client:
        await sdk_client.query(
            "Find late-1970s and 1980s films similar to 'School in the Crosshairs' (1981). "
            "Cover all major similarity axes, evaluate coverage, synthesize, then submit complete."
        )
        async for message in sdk_client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        print(f"[coordinator] {block.text.strip()}")
                    elif isinstance(block, ToolUseBlock):
                        inp = block.input or {}
                        if block.name == "Agent":
                            agent = inp.get("subagent_type") or inp.get("name") or "subagent"
                            desc = inp.get("description") or inp.get("prompt", "")[:80]
                            print(f"[dispatch]   → {agent}: {desc}")
                        else:
                            print(f"[tool_use]   {block.name}({json.dumps(inp)[:120]})")
                    elif isinstance(block, ToolResultBlock):
                        content = str(block.content)[:120] if block.content else ""
                        print(f"[tool_result] {content}")
            elif isinstance(message, TaskStartedMessage):
                print(f"[subagent_start] task_id={message.task_id}  type={message.task_type}  {message.description or ''}")
            elif isinstance(message, TaskProgressMessage):
                tool_name = message.last_tool_name or ""
                desc = message.description or ""
                print(f"[subagent_progress] task={message.task_id}  tool={tool_name}  {desc[:100]}")
            elif isinstance(message, ResultMessage):
                cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "?"
                print(f"[result] turns={message.num_turns}  cost={cost}  stop={message.stop_reason}")
            elif isinstance(message, SystemMessage):
                pass  # heartbeat / init messages, not actionable


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    await run()
    print(f"\nScratchpads → {FINDINGS_DIR}")
    print(f"Synthesis   → {SYNTHESIS_DIR}")


anyio.run(main)
