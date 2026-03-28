import anyio
from pathlib import Path
from dotenv import load_dotenv

from lib.coordinator import run_coordinator
from lib.coverage_report import print_trace, coverage_report
from lib.templates import load_data

load_dotenv(Path(__file__).parent.parent / ".env")


async def main() -> None:
    job_posting = load_data("job_posting.txt")
    resume = load_data("resume.txt")

    trace, _ = await run_coordinator(job_posting, resume)

    print_trace(trace)
    coverage_report(trace)


anyio.run(main)
