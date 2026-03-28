import json
from dataclasses import dataclass, field
from anthropic import AsyncAnthropic

from claude_agent_sdk import tool

from lib.logger import log, ts
from tools.screening_agent import call_screening_agent


@dataclass
class CoordinatorState:
    job_posting: str
    resume: str
    partition_by_name: dict
    anthropic_client: AsyncAnthropic
    model: str
    trace: list = field(default_factory=list)
    final_verdict: dict | None = None
    _step_counter: list = field(default_factory=lambda: [0])


def make_coordinator_tools(state: CoordinatorState) -> list:
    """Return the three decorated MCP tool functions bound to *state*."""

    @tool(
        "screening_agent",
        "Runs a specialist screening agent on one specific angle of candidate fit. "
        "Call once per screening dimension with a focused question. "
        "Each call receives the full job posting and resume scoped to the partition.",
        {"partition_agent": str, "question": str},
    )
    async def mcp_screening_agent(args: dict) -> dict:
        state._step_counter[0] += 1
        step = state._step_counter[0]

        partition_agent_name = args.get("partition_agent", "unknown")
        question = args["question"]
        partition = state.partition_by_name.get(partition_agent_name)

        log.delegate(step, partition_agent_name, question)
        result = await call_screening_agent(
            state.anthropic_client, state.model,
            question, state.job_posting, state.resume,
            partition=partition,
        )
        log.spoke_result(partition_agent_name, result)

        state.trace.append({
            "step": step,
            "partition_agent": partition_agent_name,
            "question": question,
            "response": result,
            "timestamp": ts(),
        })
        return {"content": [{"type": "text", "text": result}]}

    @tool(
        "evaluate_coverage",
        "Evaluate whether the screening findings so far are sufficient to make a "
        "confident recommendation. Call this after all partition agents have reported. "
        "Returns a coverage score, list of gaps, and whether the coverage is sufficient.",
        {"findings_summary": str, "coverage_score": int, "gaps": list, "sufficient": bool},
    )
    async def mcp_evaluate_coverage(args: dict) -> dict:
        step = state._step_counter[0]
        score = args.get("coverage_score", "?")
        gaps = args.get("gaps", [])
        sufficient = args.get("sufficient", False)
        log.coverage(step, score, sufficient, gaps)
        payload = json.dumps({"coverage_score": score, "gaps": gaps, "sufficient": sufficient})
        return {"content": [{"type": "text", "text": payload}]}

    @tool(
        "submit_final",
        "Submit the final hiring recommendation. Call this ONLY after "
        "evaluate_coverage returns sufficient=true (or after gap-filling follow-ups). "
        "This is the only valid way to conclude the screening. "
        "verdict must be one of: HIRE, MAYBE, PASS.",
        {"verdict": str, "rationale": str, "key_strengths": list, "key_concerns": list},
    )
    async def mcp_submit_final(args: dict) -> dict:
        state.final_verdict = {
            "verdict":       args.get("verdict"),
            "rationale":     args.get("rationale"),
            "key_strengths": args.get("key_strengths", []),
            "key_concerns":  args.get("key_concerns", []),
        }
        log.final(state.final_verdict)
        return {"content": [{"type": "text", "text": "Recommendation submitted."}]}

    return [mcp_screening_agent, mcp_evaluate_coverage, mcp_submit_final]
