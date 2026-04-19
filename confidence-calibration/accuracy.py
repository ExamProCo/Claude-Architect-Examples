"""
Accuracy tracking with field-level and document-level breakdowns.

Compares Claude's extractions against CUAD ground truth answers.
The key insight: aggregate accuracy hides per-field variance.
Some clause types (e.g. Document Name) are very reliable;
others (e.g. Non-Compete) need human review almost every time.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


@dataclass
class FieldStats:
    field_name: str
    total: int = 0
    correct: int = 0
    auto_approved: int = 0
    reviewed: int = 0
    confidence_sum: float = 0.0

    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def avg_confidence(self) -> float:
        return self.confidence_sum / self.total if self.total else 0.0

    def calibration_gap(self) -> float:
        """Positive = overconfident, negative = underconfident."""
        return self.avg_confidence() - self.accuracy()


@dataclass
class DocumentStats:
    document_title: str
    total: int = 0
    correct: int = 0
    auto_approved: int = 0

    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def auto_approve_rate(self) -> float:
        return self.auto_approved / self.total if self.total else 0.0


@dataclass
class AccuracyTracker:
    field_stats: dict[str, FieldStats] = field(default_factory=dict)
    doc_stats: dict[str, DocumentStats] = field(default_factory=dict)
    _total: int = 0
    _correct: int = 0

    def record(
        self,
        document_title: str,
        field_name: str,
        predicted: Optional[str],
        ground_truth: list[str],  # CUAD can have multiple valid answers
        confidence: float,
        routing: str,
    ) -> bool:
        """Record one prediction and return whether it was correct."""
        is_correct = _matches(predicted, ground_truth)

        # Field stats
        if field_name not in self.field_stats:
            self.field_stats[field_name] = FieldStats(field_name=field_name)
        fs = self.field_stats[field_name]
        fs.total += 1
        fs.confidence_sum += confidence
        if is_correct:
            fs.correct += 1
        if routing == "auto_approve":
            fs.auto_approved += 1
        else:
            fs.reviewed += 1

        # Document stats
        if document_title not in self.doc_stats:
            self.doc_stats[document_title] = DocumentStats(document_title=document_title)
        ds = self.doc_stats[document_title]
        ds.total += 1
        if is_correct:
            ds.correct += 1
        if routing == "auto_approve":
            ds.auto_approved += 1

        self._total += 1
        if is_correct:
            self._correct += 1

        return is_correct

    def overall_accuracy(self) -> float:
        return self._correct / self._total if self._total else 0.0

    def print_field_breakdown(self, top_n: int = 20) -> None:
        """Print per-field accuracy sorted by accuracy ascending (worst first)."""
        stats = sorted(self.field_stats.values(), key=lambda s: s.accuracy())[:top_n]

        t = Table(
            title="Field-Level Accuracy Breakdown (worst → best)",
            box=box.SIMPLE_HEAD,
        )
        t.add_column("Field", min_width=28)
        t.add_column("Accuracy", justify="right")
        t.add_column("Avg Conf", justify="right")
        t.add_column("Calibration Gap", justify="right")
        t.add_column("Auto-Approved", justify="right")
        t.add_column("N", justify="right")

        for s in stats:
            acc = s.accuracy()
            gap = s.calibration_gap()
            gap_str = f"[red]+{gap:.2f}[/red]" if gap > 0.05 else (
                f"[yellow]{gap:.2f}[/yellow]" if gap < -0.05 else f"[green]{gap:.2f}[/green]"
            )
            t.add_row(
                s.field_name,
                f"{acc:.0%}",
                f"{s.avg_confidence():.0%}",
                gap_str,
                f"{s.auto_approved}/{s.total}",
                str(s.total),
            )

        console.print(t)

    def print_document_breakdown(self) -> None:
        """Print per-document accuracy sorted descending."""
        stats = sorted(self.doc_stats.values(), key=lambda s: s.accuracy(), reverse=True)

        t = Table(title="Document-Level Accuracy Breakdown", box=box.SIMPLE_HEAD)
        t.add_column("Document", max_width=50)
        t.add_column("Accuracy", justify="right")
        t.add_column("Auto-Approve Rate", justify="right")
        t.add_column("Fields", justify="right")

        for s in stats:
            acc = s.accuracy()
            color = "green" if acc >= 0.8 else ("yellow" if acc >= 0.6 else "red")
            t.add_row(
                s.document_title[:50],
                f"[{color}]{acc:.0%}[/{color}]",
                f"{s.auto_approve_rate():.0%}",
                str(s.total),
            )

        console.print(t)

    def print_summary(self) -> None:
        console.rule("[bold]Overall Results[/bold]")
        console.print(f"  Total predictions : {self._total}")
        console.print(f"  Overall accuracy  : [bold]{self.overall_accuracy():.1%}[/bold]")
        auto = sum(s.auto_approved for s in self.field_stats.values())
        console.print(f"  Auto-approved     : {auto} / {self._total} ({auto/self._total:.0%})")


def _matches(predicted: Optional[str], ground_truth: list[str]) -> bool:
    """
    Fuzzy match: correct if predicted text overlaps substantially with any ground truth span,
    or both are absent.
    """
    gt_absent = len(ground_truth) == 0 or all(g.strip() == "" for g in ground_truth)

    if predicted is None or predicted.strip() == "":
        return gt_absent  # both say "not present" → correct

    if gt_absent:
        return False  # Claude found something where there's nothing → wrong

    pred_lower = predicted.lower().strip()
    for gt in ground_truth:
        gt_lower = gt.lower().strip()
        if not gt_lower:
            continue
        # Consider correct if predicted is a substring of GT or GT is a substring of predicted
        if pred_lower in gt_lower or gt_lower in pred_lower:
            return True
        # Jaccard token overlap ≥ 0.5
        pred_tokens = set(pred_lower.split())
        gt_tokens = set(gt_lower.split())
        if pred_tokens and gt_tokens:
            overlap = len(pred_tokens & gt_tokens) / len(pred_tokens | gt_tokens)
            if overlap >= 0.5:
                return True

    return False
