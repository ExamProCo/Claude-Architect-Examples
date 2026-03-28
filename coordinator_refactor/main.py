import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic, DefaultAioHttpClient

from lib.coordinator import Coordinator, coordinator_prompt
from lib.coverage_report import print_trace, coverage_report
from lib.templates import load_data

load_dotenv(Path(__file__).parent.parent / ".env")


async def main():
    async with AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        http_client=DefaultAioHttpClient(),
    ) as client:
        job_posting = load_data("job_posting.txt")
        resume = load_data("resume.txt")

        trace, _ = await Coordinator.run(client, coordinator_prompt, job_posting, resume)

        print_trace(trace)
        coverage_report(trace)


asyncio.run(main())
