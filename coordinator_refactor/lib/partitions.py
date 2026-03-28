import json
from lib.logger import log
from lib.templates import load_prompt, render


class Partitions:

    @staticmethod
    async def generate(client, model: str, job_posting: str, resume: str) -> list[dict]:
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=load_prompt("partition_planner"),
                messages=[{"role": "user", "content": render(
                    "msg_generate_partitions",
                    job_posting=job_posting,
                    resume=resume,
                )}],
            )
            text = response.content[0].text.strip() if response.content else ""
            if not text:
                raise ValueError("Partition planner returned empty response")
            if text.startswith("```"):
                text = "\n".join(
                    line for line in text.splitlines()
                    if not line.startswith("```")
                ).strip()
            return json.loads(text)
        except json.JSONDecodeError as exc:
            log.error("partition JSON invalid: %s", exc)
            raise
        except Exception as exc:
            log.error("generate_partitions: %s", exc)
            raise

    @staticmethod
    def validate_overlap(partitions: list[dict]) -> None:
        seen = []
        for p in partitions:
            for item in p.get("scope", {}).get("cover", []):
                if item.lower() in [c.lower() for c in seen]:
                    log.warn("overlap detected item=%s", item)
                seen.append(item)

    @staticmethod
    def index_by_agent(partitions: list[dict]) -> dict[str, dict]:
        return {p["agent"]: p for p in partitions}

    @staticmethod
    def build_initial_messages(partitions: list[dict], job_posting: str, resume: str) -> list[dict]:
        partition_context = (
            "SCREENING PARTITIONS (non-overlapping scopes pre-planned for this candidate):\n"
            + json.dumps(partitions, indent=2)
        )
        return [{"role": "user", "content": render(
            "msg_coordinator_init",
            partition_context=partition_context,
            job_posting=job_posting,
            resume=resume,
        )}]
