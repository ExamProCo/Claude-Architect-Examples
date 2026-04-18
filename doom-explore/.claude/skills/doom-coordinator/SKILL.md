---
name: doom-coordinator
description: Coordinates DOOM codebase exploration in the doom-explore/ directory. Use this skill whenever you are about to dispatch a doom-explorer or doom-synthesizer subagent, when starting a session in doom-explore/, when verifying task completion, or when resuming failed exploration tasks. Handles manifest.json state, reconciliation of stuck tasks, post-dispatch verification, and resume-from-failure flow.
---

# doom-coordinator

You are the coordinator for DOOM codebase exploration. Full design is in
`SPEC.md`. The subagent contracts are in `.claude/agents/doom-explorer.md` and
`.claude/agents/doom-synthesizer.md`. Your job is to orchestrate them and keep
`manifest.json` consistent.

## Hard rules

1. **Never Read or Grep `doom-src/` yourself.** The subagent does that.
   Doing it defeats the context-isolation design.
2. **Never dispatch a subagent without following this loop.**
3. **Never hand-edit `manifest.json` status fields.** Use `coordinator.py`.

## On session start

```bash
python coordinator.py reconcile   # mark stuck 'running' rows as 'failed'
python coordinator.py stuck       # list rows needing re-dispatch
```

If `stuck` lists rows, offer the user to resume them before new work.

## Before each dispatch

1. Allocate the next task ID (`t-NNNN`, zero-padded, monotonic).
2. Append a row to `manifest.json`: `status: "pending"`, correct `kind`
   (`explore` or `synthesize`). For synthesize, fill `inputs`.
3. Dispatch via the `Agent` tool. Project `.claude/agents/` types are not
   registered with the harness, so use `subagent_type: general-purpose` and
   tell the agent to follow the appropriate `.claude/agents/*.md` contract.

## After each dispatch

```bash
python coordinator.py verify <task_id>
```

- Prints `ok` if the subagent already flipped the row to `complete`.
- Otherwise marks the row `failed` with a reason so nothing stays stuck.

## Resuming a failed task

Re-dispatch the same subagent type with:

- same `task_id`
- `resume_from: <artifact path from manifest>`

The subagent must **append** a `## Update <UTC ISO timestamp>` section rather
than overwrite. That rule lives in the subagent contracts; the coordinator
just needs to pass `resume_from`.

## Cost

Subagents use `model: claude-haiku-4-5-20251001` (set in each agent's
frontmatter — don't override unless the user asks).
