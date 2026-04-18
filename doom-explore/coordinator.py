#!/usr/bin/env python3
"""Coordinator helper for doom-explore.

Commands:
  reconcile           Scan manifest for stuck 'running' rows (no heartbeat in
                      the last STALE_MINUTES). Mark them 'failed' with a reason
                      and preserve any partial artifact path.
  verify <task_id>    Check a single task row flipped to 'complete' after a
                      dispatch. If not, mark it 'failed' with the given reason
                      (pass reason as 3rd arg; default "dispatch returned but
                      manifest not updated").
  stuck               List rows that need re-dispatch (status 'failed' or
                      'running' past the stale window) along with their
                      resume_from paths.

Usage:
  python coordinator.py reconcile
  python coordinator.py verify t-0006 "subagent returned without marking complete"
  python coordinator.py stuck
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "manifest.json"
STALE_MINUTES = 10


def load() -> dict:
    return json.loads(MANIFEST.read_text())


def save(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=2) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def reconcile() -> int:
    m = load()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)
    changed = 0
    for task in m["tasks"]:
        if task["status"] != "running":
            continue
        started = parse_iso(task.get("started_at"))
        if started and started > cutoff:
            continue
        task["status"] = "failed"
        task["finished_at"] = now_iso()
        prior = task.get("notes") or ""
        task["notes"] = (
            f"reconciled: stuck in 'running' past {STALE_MINUTES}m window"
            + (f"; prior: {prior}" if prior else "")
        )
        changed += 1
        print(f"marked {task['id']} failed (artifact preserved: {task.get('artifact')})")
    save(m)
    print(f"reconcile: {changed} row(s) updated")
    return 0


def verify(task_id: str, reason: str) -> int:
    m = load()
    for task in m["tasks"]:
        if task["id"] != task_id:
            continue
        if task["status"] == "complete":
            print(f"{task_id}: ok (complete)")
            return 0
        task["status"] = "failed"
        task["finished_at"] = now_iso()
        task["notes"] = reason
        save(m)
        print(f"{task_id}: marked failed — {reason}")
        return 0
    print(f"{task_id}: not found", file=sys.stderr)
    return 1


def stuck() -> int:
    m = load()
    rows = [t for t in m["tasks"] if t["status"] in ("failed", "running")]
    if not rows:
        print("none")
        return 0
    for t in rows:
        print(f"{t['id']}  {t['status']:8s}  resume_from={t.get('artifact')}  — {t['question']}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "reconcile":
        return reconcile()
    if cmd == "verify":
        if len(argv) < 3:
            print("verify requires <task_id> [reason]", file=sys.stderr)
            return 1
        reason = argv[3] if len(argv) >= 4 else "dispatch returned but manifest not updated"
        return verify(argv[2], reason)
    if cmd == "stuck":
        return stuck()
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
