from datetime import datetime, timezone
from pathlib import Path

from lib.logger import log

_REPORTS_DIR = Path(__file__).parent.parent / "reports"
_REPORTS_DIR.mkdir(exist_ok=True)

DIMENSIONS = [
    ("Technical / Hard Skill Match",        ["skill", "python", "fastapi", "keyword", "technical", "required"]),
    ("Experience Depth / Seniority",         ["depth", "senior", "experience", "level", "scope"]),
    ("Red Flags / Disqualifiers",            ["red flag", "gap", "hop", "disqualif", "concern"]),
    ("Soft Skills / Working Style",          ["soft", "communication", "collaborat", "working style", "team"]),
    ("Growth Trajectory / Potential",        ["growth", "trajectory", "potential", "progression", "future"]),
    ("Nice-to-Haves and Trade-offs",         ["nice", "trade", "bonus", "preferred", "optional"]),
    ("Compensation / Motivation / Timeline", ["compens", "salary", "motiv", "timeline", "expectation"]),
    ("Team / Culture Fit",                   ["culture", "team fit", "team dynamic", "environment"]),
    ("Compensating Strengths for Gaps",      ["compensat", "offset", "strength", "despite", "mitigat"]),
]


def _covered(qs: list[str], keywords: list[str]) -> bool:
    combined = " ".join(qs).lower()
    return any(kw in combined for kw in keywords)


def print_trace(trace: list[dict]) -> None:
    for i, entry in enumerate(trace, 1):
        log.trace(i, entry)


def coverage_report(trace: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H%M%S")
    report_path = _REPORTS_DIR / f"report_{timestamp}.md"

    dynamic_qs = [e["question"] for e in trace]
    results = [(label, _covered(dynamic_qs, kws)) for label, kws in DIMENSIONS]
    covered_count = sum(1 for _, ok in results if ok)

    lines = [
        f"# Screening Coverage Report",
        f"",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"",
        f"---",
        f"",
        f"## Coverage Summary",
        f"",
        f"{covered_count} of {len(DIMENSIONS)} dimensions covered",
        f"",
        f"| Dimension | Status |",
        f"|-----------|--------|",
    ]
    for label, ok in results:
        status = "✅ Covered" if ok else "❌ Not covered"
        lines.append(f"| {label} | {status} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Question Trace ({len(trace)} questions asked)",
        f"",
    ]
    for i, entry in enumerate(trace, 1):
        lines += [
            f"### {i}. {entry['partition_agent']}",
            f"",
            f"**Q:** {entry['question']}",
            f"",
            f"**A:** {entry['response']}",
            f"",
        ]

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nReport written to: {report_path}")

    # Still log the dimension summary for the run log
    for label, ok in results:
        log.coverage_dimension(label, ok)
