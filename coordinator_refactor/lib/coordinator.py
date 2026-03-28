import json
from lib.logger import log, ts
from lib.partitions import Partitions
from lib.templates import load_prompt, load_tools
from tools.screening_agent import call_screening_agent

model = "claude-haiku-4-5-20251001"
coordinator_prompt = load_prompt("dynamic_coordinator")
tools = load_tools()


class Coordinator:

    @staticmethod
    async def call(client, system_prompt, messages):
        return await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

    @staticmethod
    def log_reasoning(response, step):
        for block in response.content:
            if hasattr(block, "text") and block.text.strip():
                log.coordinator(step, block.text.strip())

    @staticmethod
    async def handle_screening_agent(client, block, step, partition_by_name, job_posting, resume, trace):
        partition_agent = block.input.get("partition_agent", "unknown")
        question = block.input["question"]
        partition = partition_by_name.get(partition_agent)

        log.delegate(step, partition_agent, question)
        result = await call_screening_agent(client, model, question, job_posting, resume, partition=partition)
        log.spoke_result(partition_agent, result)

        trace.append({
            "step": step,
            "partition_agent": partition_agent,
            "question": question,
            "response": result,
            "timestamp": ts(),
        })

        return {"type": "tool_result", "tool_use_id": block.id, "content": result}

    @staticmethod
    def handle_evaluate_coverage(block, step):
        score = block.input.get("coverage_score", "?")
        gaps = block.input.get("gaps", [])
        sufficient = block.input.get("sufficient", False)
        log.coverage(step, score, sufficient, gaps)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps({"coverage_score": score, "gaps": gaps, "sufficient": sufficient}),
        }

    @staticmethod
    def handle_submit_final(block):
        verdict = {
            "verdict":       block.input.get("verdict"),
            "rationale":     block.input.get("rationale"),
            "key_strengths": block.input.get("key_strengths", []),
            "key_concerns":  block.input.get("key_concerns", []),
        }
        log.final(verdict)
        return verdict, {"type": "tool_result", "tool_use_id": block.id, "content": "Recommendation submitted."}

    @staticmethod
    async def process_tool_calls(client, response, step, partition_by_name, job_posting, resume, trace):
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "screening_agent":
                tool_results.append(await Coordinator.handle_screening_agent(
                    client, block, step, partition_by_name, job_posting, resume, trace
                ))
            elif block.name == "evaluate_coverage":
                tool_results.append(Coordinator.handle_evaluate_coverage(block, step))
            elif block.name == "submit_final":
                verdict, tool_result = Coordinator.handle_submit_final(block)
                tool_results.append(tool_result)
                return verdict, tool_results
        return None, tool_results

    @staticmethod
    async def run(client, system_prompt, job_posting, resume):
        partitions = await Partitions.generate(client, model, job_posting, resume)
        Partitions.validate_overlap(partitions)

        partition_by_name = Partitions.index_by_agent(partitions)
        messages = Partitions.build_initial_messages(partitions, job_posting, resume)
        trace = []

        try:
            for step in range(1, 31):
                response = await Coordinator.call(client, system_prompt, messages)
                Coordinator.log_reasoning(response, step)

                if response.stop_reason == "end_turn":
                    log.warn("end_turn without submit_final step=%d", step)
                    break

                if response.stop_reason == "tool_use":
                    final_verdict, tool_results = await Coordinator.process_tool_calls(
                        client, response, step, partition_by_name, job_posting, resume, trace
                    )
                    messages += [
                        {"role": "assistant", "content": response.content},
                        {"role": "user",      "content": tool_results},
                    ]
                    if final_verdict:
                        return trace, final_verdict
            else:
                log.warn("step_limit_reached")
        except Exception as exc:
            log.error("coordinator_loop_failed step=%d: %s", step, exc)
            raise

        return trace, None
