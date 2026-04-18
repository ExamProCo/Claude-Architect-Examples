# DOOM Codebase Exploration — Spec & Task Breakdown

## Goal
Build a Claude Code orchestration that explores the DOOM codebase (e.g. "how does a player take damage?") without polluting the parent agent's context, persists findings externally, and supports resumable subagent tasks.

## Target Codebase
- Source: https://github.com/id-software/doom (original id Software release).
- Placed locally under `doom-src/` (cloned or submoduled).

## Design Overview

**Parent (coordinator)**
- Receives the exploration question.
- Dispatches `doom-explorer` subagents per sub-question.
- When enough scratchpads exist, dispatches `doom-synthesizer` to produce a consolidated answer.
- Never performs raw code exploration itself (keeps context clean).

**Subagent 1 — `doom-explorer`**
- Defined at `.claude/agents/doom-explorer.md`.
- Scoped tools: `Read`, `Grep`, `Glob` (read-only exploration) + `Edit`/`Write` restricted to `FINDINGS/` and `manifest.json`.
- Produces one scratchpad file per task in `FINDINGS/`.
- Updates `manifest.json` entry for its task.

**Subagent 2 — `doom-synthesizer`**
- Defined at `.claude/agents/doom-synthesizer.md`.
- Scoped tools: `Read`, `Glob`, `Write`, `Edit` (no `Grep` on source — works only from scratchpads).
- Inputs: a list of scratchpad paths (or a topic) from the coordinator.
- Output: a synthesis doc at `FINDINGS/_synthesis/<topic>.md` that cites scratchpads and answers the original question.
- Never reads DOOM source directly — prevents re-bloating context.

**State files**
- `FINDINGS/` — folder of scratchpad artifacts. One file per exploration task: `FINDINGS/<task_id>-<slug>.md`. Append-only per file.
- `FINDINGS/_synthesis/` — consolidated answers written by `doom-synthesizer`.
- `manifest.json` — task registry. Each task: `{ id, kind: "explore"|"synthesize", question, status: pending|running|complete|failed, started_at, finished_at, artifact: "FINDINGS/<file>.md", inputs: [artifact paths], notes }`.

**Resume semantics**
- On start, coordinator reads `manifest.json`.
- Any `running` or `failed` task is re-dispatched with its prior `findings_anchor` so the subagent can continue rather than restart.
- `complete` tasks are skipped; their findings are reused.

## File Layout
```
doom-explore/
  .claude/agents/
    doom-explorer.md                 # exploration subagent
    doom-synthesizer.md              # synthesis subagent
  FINDINGS/                          # scratchpad artifacts
    <task_id>-<slug>.md              # one per exploration task
    _synthesis/
      <topic>.md                     # consolidated answers
  manifest.json                      # task state registry
  PLAN.md
  SPEC.md
  doom-src/                          # clone of id-software/doom
```

## Subagent Contracts

### `doom-explorer`
Input (prompt from coordinator):
- `task_id`, `question`, optional `resume_from` (path to existing scratchpad).

Output (side effects only):
- Create or append to `FINDINGS/<task_id>-<slug>.md`.
- Update manifest entry to `complete` (or `failed` + reason).
- Return ≤150-word summary to coordinator.

### `doom-synthesizer`
Input (prompt from coordinator):
- `task_id`, `topic`, `inputs` (list of scratchpad paths).

Output (side effects only):
- Write `FINDINGS/_synthesis/<topic>.md` citing each scratchpad (`FINDINGS/<file>.md#section`).
- Update manifest entry.
- Return ≤150-word summary + path to synthesis doc.

## Task Breakdown

### T1 — Scaffold repo
- Create `FINDINGS/` and `FINDINGS/_synthesis/` (each with a `.gitkeep`).
- Create `manifest.json` with `{ "version": 1, "tasks": [] }`.
- Clone `id-software/doom` into `doom-src/`; add to `.gitignore`.

### T2 — Author `doom-explorer`
- `.claude/agents/doom-explorer.md` with frontmatter (`name`, `description`, `tools`, `model: claude-haiku-4-5-20251001`).
- Tools: `Read, Grep, Glob, Edit, Write`.
- Embed contract + scratchpad template + manifest update rules.

### T3 — Author `doom-synthesizer`
- `.claude/agents/doom-synthesizer.md` with frontmatter.
- Tools: `Read, Glob, Edit, Write` (no `Grep` — forces it to use scratchpads, not source).
- Embed synthesis template with required citations to scratchpads.

### T4 — Define manifest schema
- Document fields inline with a JSON example covering both `kind: explore` and `kind: synthesize` entries.

### T5 — Scratchpad conventions
- Each `FINDINGS/<task_id>-<slug>.md` has: **Question**, **Entry points**, **Call chain**, **Key files** (`file:line`), **Summary**, **Open follow-ups**.
- Synthesis docs cite scratchpads by relative path + section anchor.
- All files append-only; never rewrite prior entries.

### T6 — Coordinator workflow
- Parent prompt template:
  1. Load `manifest.json`.
  2. Allocate task ID, append `pending` row.
  3. Dispatch `doom-explorer` or `doom-synthesizer` via `Agent` tool.
  4. On return, verify artifact + manifest updated; else mark `failed`.

### T7 — Resume flow
- On startup, scan manifest for `running`/`failed`.
- Re-dispatch with `resume_from` pointing at the existing scratchpad path.
- Subagent appends to the same file rather than starting fresh.

### T8 — Smoke test
- Explore: "How does a player take damage?"
- Follow up with a synthesis pass over the resulting scratchpads.
- Verify parent context stayed clean (no raw source dumps).

### T9 — Failure handling
- Subagent crash → coordinator marks task `failed` with error excerpt.
- Partial scratchpad preserved; resume picks up from last section.

## Acceptance Criteria
- Parent never calls `Grep`/`Read` on `doom-src/` directly.
- All exploration output lives in `FINDINGS/` + `manifest.json`.
- `doom-synthesizer` never reads from `doom-src/`, only from `FINDINGS/`.
- Killing and restarting the parent mid-task resumes without losing prior findings.
- A new question adds exactly one manifest entry and one scratchpad file.
