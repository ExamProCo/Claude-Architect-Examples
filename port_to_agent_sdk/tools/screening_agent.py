from lib.logger import log
from lib.templates import load_prompt, render


async def call_screening_agent(
    client, model: str, question: str, job_posting: str, resume: str,
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
            system=load_prompt("screening_agent"),
            messages=[{"role": "user", "content": render(
                "msg_screening_agent",
                scope_header=scope_header,
                question=question,
                job_posting=job_posting,
                resume=resume,
            )}],
        )
        return r.content[0].text if r.content else "[no response]"
    except Exception as exc:
        log.error("screening_agent question=%s: %s", question, exc)
        return f"[ERROR: {exc}]"
