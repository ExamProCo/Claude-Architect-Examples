"""
Human review workflow for low-confidence contract extractions.

Attorneys are shown each flagged field, Claude's answer, and its reasoning.
They can confirm, correct, or defer. All decisions feed back into accuracy stats.
"""

from dataclasses import dataclass, field
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from agent import ContractAnalysis, FieldExtraction

console = Console()


@dataclass
class ReviewDecision:
    document_title: str
    field_name: str
    claude_value: Optional[str]
    final_value: Optional[str]
    confidence: float
    routing: str
    action: str  # "confirmed" | "corrected" | "deferred"


@dataclass
class ReviewSession:
    decisions: list[ReviewDecision] = field(default_factory=list)
    _quit: bool = False

    @property
    def confirmed(self) -> int:
        return sum(1 for d in self.decisions if d.action == "confirmed")

    @property
    def corrected(self) -> int:
        return sum(1 for d in self.decisions if d.action == "corrected")

    @property
    def deferred(self) -> int:
        return sum(1 for d in self.decisions if d.action == "deferred")

    @property
    def total(self) -> int:
        return len(self.decisions)

    def correction_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.corrected / self.total


def _routing_color(routing: str) -> str:
    return {"auto_approve": "green", "quick_review": "yellow", "full_review": "red"}.get(
        routing, "white"
    )


def review_analysis(analysis: ContractAnalysis, session: ReviewSession) -> None:
    """Walk an attorney through all flagged fields in a single contract."""
    flagged = analysis.flagged_fields()
    if not flagged:
        console.print(f"[green]✓ All fields auto-approved for {analysis.document_title}[/green]")
        return

    console.print(
        Panel(
            f"[bold]{analysis.document_title}[/bold]\n"
            f"Contract type: {analysis.contract_type}\n"
            f"Flagged fields: {len(flagged)} / {len(analysis.extractions)}",
            title="[yellow]Attorney Review Required[/yellow]",
        )
    )

    for extraction in flagged:
        if session._quit:
            break
        _review_field(analysis, extraction, session)

    _print_session_summary(session)


def _review_field(
    analysis: ContractAnalysis,
    extraction: FieldExtraction,
    session: ReviewSession,
) -> None:
    color = _routing_color(extraction.routing)
    label = extraction.routing.replace("_", " ").upper()

    console.print(f"\n[{color}]● {label}[/{color}]  Field: [bold]{extraction.field_name}[/bold]")
    console.print(f"  Confidence: [bold]{extraction.confidence:.0%}[/bold]")
    console.print(f"  Extracted:  {extraction.extracted_value or '[bold red]NOT FOUND[/bold red]'}")
    console.print(f"  Reasoning:  [dim]{extraction.reasoning}[/dim]")
    console.print("  [dim]\\[c]onfirm  \\[e]dit  \\[d]efer  \\[q]uit[/dim]")

    while True:
        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            session._quit = True
            return

        if choice == "c":
            session.decisions.append(
                ReviewDecision(
                    document_title=analysis.document_title,
                    field_name=extraction.field_name,
                    claude_value=extraction.extracted_value,
                    final_value=extraction.extracted_value,
                    confidence=extraction.confidence,
                    routing=extraction.routing,
                    action="confirmed",
                )
            )
            console.print("  [green]✓ Confirmed[/green]")
            return

        elif choice == "e":
            try:
                corrected = input("  New value: ").strip() or None
            except (EOFError, KeyboardInterrupt):
                session._quit = True
                return
            session.decisions.append(
                ReviewDecision(
                    document_title=analysis.document_title,
                    field_name=extraction.field_name,
                    claude_value=extraction.extracted_value,
                    final_value=corrected,
                    confidence=extraction.confidence,
                    routing=extraction.routing,
                    action="corrected",
                )
            )
            console.print(f"  [yellow]✎ Corrected → {corrected}[/yellow]")
            return

        elif choice == "d":
            session.decisions.append(
                ReviewDecision(
                    document_title=analysis.document_title,
                    field_name=extraction.field_name,
                    claude_value=extraction.extracted_value,
                    final_value=None,
                    confidence=extraction.confidence,
                    routing=extraction.routing,
                    action="deferred",
                )
            )
            console.print("  [dim]→ Deferred[/dim]")
            return

        elif choice == "q":
            session._quit = True
            return


def _print_session_summary(session: ReviewSession) -> None:
    if session.total == 0:
        return
    t = Table(title="Review Session Summary", box=box.SIMPLE)
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Total reviewed", str(session.total))
    t.add_row("Confirmed", f"[green]{session.confirmed}[/green]")
    t.add_row("Corrected", f"[yellow]{session.corrected}[/yellow]")
    t.add_row("Deferred", f"[dim]{session.deferred}[/dim]")
    t.add_row("Correction rate", f"{session.correction_rate():.0%}")
    console.print(t)
