"""
Legal Contract Intake Review System
=====================================
Use Case:
  A law firm receives commercial contracts for intake review. Before an attorney
  reads each contract, this system extracts 30 key clause types using Claude.
  Extractions are routed by confidence:

    ≥ 80%  → auto-approved, no attorney time needed
    55–79% → quick review (attorney confirms or corrects in ~10 seconds)
    < 55%  → full review (attorney reads the context)

  Accuracy is tracked per field and per document — not just as an aggregate —
  so the firm knows which clause types are reliable vs. which always need review.

  Stratified sampling ensures the evaluation covers all 30 clause types evenly,
  not just the most common ones (which would inflate the headline number).

Run:
  python main.py explore          # explore CUAD dataset structure
  python main.py run --contracts 3 --review    # run pipeline with human review
  python main.py run --contracts 5             # run pipeline, no interactive review
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from datasets import load_dataset

from agent import extract_contract_fields, CLAUSE_TYPES
from accuracy import AccuracyTracker
from review import ReviewSession, review_analysis

load_dotenv(Path(__file__).parent.parent / ".env")
console = Console()

# ── Data loading ──────────────────────────────────────────────────────────────

def load_cuad() -> list[dict]:
    """
    Load CUAD and flatten into a list of documents.
    Each document: {title, context, qas: [{question, answers, is_impossible}]}
    """
    console.print("[dim]Loading CUAD dataset from HuggingFace…[/dim]")
    ds = load_dataset(
        "chenghao/cuad_qa",
        verification_mode="no_checks",
    )
    # chenghao/cuad_qa is a flat dataset: one row per QA pair.
    # Group rows by (title, context) to reconstruct per-contract documents.
    split = ds["train"]
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in split:
        key = (row["title"], row["context"])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(
            {
                "id": row["id"],
                "question": row["question"],
                "answers": row["answers"],
            }
        )
    documents = [
        {"title": title, "context": context, "qas": qas_list}
        for (title, context), qas_list in grouped.items()
    ]
    return documents


def _build_gt_map(doc: dict) -> dict[str, list[str]]:
    """Return {short_field_name: [ground_truth_text, ...]} for a document."""
    gt = {}
    for qa in doc["qas"]:
        # CUAD questions are long; we match by checking if a CLAUSE_TYPE appears in the question
        matched_field = _match_field(qa["question"])
        if matched_field:
            texts = list(qa["answers"].get("text", []))
            if isinstance(texts, str):
                texts = [texts]
            # Handle nested list from HuggingFace format
            flat = []
            for t in texts:
                if isinstance(t, list):
                    flat.extend(t)
                else:
                    flat.append(t)
            gt[matched_field] = flat
    return gt


_field_cache: dict[str, str | None] = {}

def _match_field(question: str) -> str | None:
    if question in _field_cache:
        return _field_cache[question]
    q_lower = question.lower()
    for clause in CLAUSE_TYPES:
        if clause.lower() in q_lower:
            _field_cache[question] = clause
            return clause
    _field_cache[question] = None
    return None


# ── Stratified sampling ───────────────────────────────────────────────────────

def stratified_sample(documents: list[dict], n: int, seed: int = 42) -> list[dict]:
    """
    Sample n documents ensuring each clause type is represented.
    Groups docs by which clause types have non-empty answers, then samples evenly.
    """
    rng = random.Random(seed)

    # Build buckets: clause_type → [doc_idx, ...]
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, doc in enumerate(documents):
        for qa in doc["qas"]:
            field = _match_field(qa["question"])
            if not field:
                continue
            answers = qa["answers"].get("text", [])
            if isinstance(answers, str):
                answers = [answers]
            has_answer = any(
                (t if isinstance(t, str) else (t[0] if t else "")).strip()
                for t in answers
            )
            if has_answer:
                buckets[field].append(i)

    selected_idxs: set[int] = set()
    # Round-robin across clause types until we have n docs
    clause_keys = list(buckets.keys())
    rng.shuffle(clause_keys)
    cycle_pos = 0
    attempts = 0
    while len(selected_idxs) < n and attempts < n * 10:
        key = clause_keys[cycle_pos % len(clause_keys)]
        cycle_pos += 1
        attempts += 1
        candidates = [i for i in buckets[key] if i not in selected_idxs]
        if candidates:
            selected_idxs.add(rng.choice(candidates))

    # Fill remainder randomly if needed
    remaining = [i for i in range(len(documents)) if i not in selected_idxs]
    rng.shuffle(remaining)
    while len(selected_idxs) < n and remaining:
        selected_idxs.add(remaining.pop())

    return [documents[i] for i in sorted(selected_idxs)[:n]]


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_explore(documents: list[dict]) -> None:
    """Print dataset overview statistics."""
    console.rule("[bold]CUAD Dataset Explorer[/bold]")
    console.print(f"  Total documents : {len(documents)}")

    # Clause type coverage
    coverage: dict[str, int] = defaultdict(int)
    for doc in documents:
        for qa in doc["qas"]:
            field = _match_field(qa["question"])
            if not field:
                continue
            answers = qa["answers"].get("text", [])
            if isinstance(answers, str):
                answers = [answers]
            has_answer = any(
                (t if isinstance(t, str) else (t[0] if t else "")).strip()
                for t in answers
            )
            if has_answer:
                coverage[field] += 1

    t = Table(title="Clause Type Coverage (# docs with answer)", box=box.SIMPLE_HEAD)
    t.add_column("Clause Type", min_width=30)
    t.add_column("# Documents", justify="right")
    t.add_column("Coverage", justify="right")
    for clause in sorted(coverage, key=coverage.get, reverse=True):
        pct = coverage[clause] / len(documents)
        bar = "█" * int(pct * 20)
        t.add_row(clause, str(coverage[clause]), f"{pct:.0%} {bar}")
    console.print(t)

    # Sample document titles
    console.print("\n[bold]Sample document titles:[/bold]")
    for doc in documents[:8]:
        console.print(f"  • {doc['title']}")


def cmd_run(documents: list[dict], n_contracts: int, human_review: bool) -> None:
    """Run the full pipeline: sample → extract → route → review → report accuracy."""
    console.rule("[bold]Legal Contract Intake Pipeline[/bold]")

    sample = stratified_sample(documents, n_contracts)
    console.print(
        Panel(
            f"Contracts selected : {len(sample)} (stratified)\n"
            f"Fields per contract: {len(CLAUSE_TYPES)}\n"
            f"Human review       : {'enabled' if human_review else 'disabled'}\n"
            f"Auto-approve at    : ≥80% confidence\n"
            f"Flag for review at : <80% confidence",
            title="Pipeline Configuration",
        )
    )

    tracker = AccuracyTracker()
    session = ReviewSession()

    for i, doc in enumerate(sample, 1):
        title = doc["title"]
        console.print(f"\n[dim][{i}/{len(sample)}] Extracting: {title[:60]}…[/dim]")

        analysis = extract_contract_fields(
            contract_text=doc["context"],
            document_id=title,
            document_title=title,
        )

        gt_map = _build_gt_map(doc)

        for extraction in analysis.extractions:
            gt = gt_map.get(extraction.field_name, [])
            tracker.record(
                document_title=title,
                field_name=extraction.field_name,
                predicted=extraction.extracted_value,
                ground_truth=gt,
                confidence=extraction.confidence,
                routing=extraction.routing,
            )

        auto_count = len(analysis.auto_approved_fields())
        flag_count = len(analysis.flagged_fields())
        console.print(
            f"  Auto-approved: [green]{auto_count}[/green]  "
            f"Flagged for review: [yellow]{flag_count}[/yellow]  "
            f"Avg confidence: {analysis.avg_confidence():.0%}"
        )

        if human_review and not session._quit:
            review_analysis(analysis, session)

    # ── Results ──
    console.rule("[bold]Results[/bold]")
    tracker.print_summary()
    console.print()
    tracker.print_field_breakdown()
    console.print()
    tracker.print_document_breakdown()

    if human_review and session.total > 0:
        console.rule("[bold]Human Review Impact[/bold]")
        console.print(f"  Items reviewed  : {session.total}")
        console.print(f"  Confirmed       : [green]{session.confirmed}[/green]")
        console.print(f"  Corrected       : [yellow]{session.corrected}[/yellow]")
        console.print(f"  Correction rate : {session.correction_rate():.0%}  ← "
                      "this is accuracy Claude missed without review")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Legal Contract Intake Review System")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("explore", help="Explore CUAD dataset statistics")

    run_p = sub.add_parser("run", help="Run the extraction pipeline")
    run_p.add_argument("--contracts", type=int, default=3, help="Number of contracts to process")
    run_p.add_argument("--review", action="store_true", help="Enable interactive human review")

    args = parser.parse_args()

    documents = load_cuad()

    if args.cmd == "explore":
        cmd_explore(documents)
    elif args.cmd == "run":
        cmd_run(documents, n_contracts=args.contracts, human_review=args.review)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
