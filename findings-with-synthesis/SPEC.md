# Film Research with Findings & Synthesis — Spec

## Goal

Evolve the current single-agent film research script (`main.py`) into a two-agent system: a **movie-explorer** that researches specific similarity angles and deposits structured scratchpads, and a **movie-synthesizer** that reads those scratchpads (never the web) and produces a final, source-attributed synthesis. The coordinator (upgraded `main.py`) orchestrates both.

The three synthesis goals to satisfy:
1. **Provenance preservation** — every claim carries a claim→source mapping; summarization never strips attribution.
2. **Conflict annotation** — when two sources give conflicting statistics or facts, both are retained with source labels rather than one being silently dropped.
3. **Temporal metadata** — every finding records `published_at` / `accessed_at` so date differences are never misread as factual contradictions.

---

## Design Overview

### Parent — coordinator (`main.py`)
- Receives the research question and similarity axes.
- Dispatches `movie-explorer` subagents, one per axis.
- When enough scratchpads exist, dispatches `movie-synthesizer`.
- Never performs research itself; only calls tools to record, evaluate, and finalize.

### Subagent 1 — `movie-explorer`
- Defined at `.claude/agents/movie-explorer.md`.
- Tools: `WebSearch`, `WebFetch`, `Read`, `Write`, `Edit` — model knowledge alone is not provenance; every claim must cite a verified external URL with a verbatim quote.
- Produces one scratchpad file per task in `FINDINGS/`.
- Updates `manifest.json` entry for its task.
- Output must be a `FindingList` JSON object matching the existing schema.

### Subagent 2 — `movie-synthesizer`
- Defined at `.claude/agents/movie-synthesizer.md`.
- Tools: `Read`, `Glob` (reads only from `FINDINGS/`; never accesses external sources).
- Inputs: list of scratchpad paths from coordinator.
- Output: `FINDINGS/_synthesis/<topic>.md` — a structured synthesis doc that preserves claim→source mappings, flags conflicts, and notes temporal deltas.
- Never re-researches; works exclusively from scratchpad content.

---

## State Files

| Path | Purpose |
|---|---|
| `FINDINGS/<task_id>-<slug>.md` | One scratchpad per explorer task (append-only) |
| `FINDINGS/_synthesis/<topic>.md` | Consolidated synthesis written by movie-synthesizer |
| `manifest.json` | Task registry — status, artifact paths, timestamps |

---

## Scratchpad Format (`FINDINGS/<task_id>-<slug>.md`)

Each explorer scratchpad must contain these sections:

```markdown
## Question
<the specific similarity angle researched>

## Findings
<FindingList JSON block — validated against FindingList schema>

## Conflicts
<If two sources disagree on a fact, list both with attribution. If none, write "none.">

## Open Follow-ups
<questions this angle raised that another axis should cover>
```

---

## Synthesis Doc Format (`FINDINGS/_synthesis/<topic>.md`)

```markdown
## Topic
<original research question>

## Sources Consulted
- [task_id] FINDINGS/<file>.md — one-line summary of axis

## Synthesis
<prose with inline citations: "Film X (dir. Y, YYYY) [finding_001]">

## Claim–Source Map
| claim_id | claim summary | source scratchpad | confidence | published_at |
|---|---|---|---|---|

## Conflicts Retained
| conflict_id | description | source_a | source_b |
|---|---|---|---|

## Temporal Notes
<any findings where date gaps could be mistaken for contradictions>
```

---

## Manifest Schema

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "t-0001",
      "kind": "explore",
      "question": "Japanese supernatural school films 1975-1989",
      "status": "pending | running | complete | failed",
      "started_at": "2026-04-18T00:00:00Z",
      "finished_at": null,
      "artifact": "FINDINGS/t-0001-japanese-supernatural.md",
      "inputs": [],
      "notes": ""
    },
    {
      "id": "t-0010",
      "kind": "synthesize",
      "question": "Full synthesis: films similar to School in the Crosshairs",
      "status": "pending",
      "started_at": null,
      "finished_at": null,
      "artifact": "FINDINGS/_synthesis/school-in-the-crosshairs.md",
      "inputs": ["FINDINGS/t-0001-japanese-supernatural.md", "FINDINGS/t-0002-teen-psychic.md"],
      "notes": ""
    }
  ]
}
```

---

## Subagent Contracts

### `movie-explorer`
**Input** (from coordinator prompt):
- `task_id`, `question` (the specific similarity axis), optional `resume_from` (path to existing scratchpad).

**Output** (side effects only):
- Create or append to `FINDINGS/<task_id>-<slug>.md` using the scratchpad format above.
- Update manifest row to `complete` (or `failed` + reason in `notes`).
- Return ≤150-word summary to coordinator.

### `movie-synthesizer`
**Input** (from coordinator prompt):
- `task_id`, `topic`, `inputs` (list of scratchpad paths).

**Output** (side effects only):
- Write `FINDINGS/_synthesis/<topic>.md` using the synthesis doc format above.
- Preserve all claim→source mappings from input scratchpads.
- Annotate conflicts; never silently resolve them.
- Update manifest row.
- Return ≤150-word summary + path to synthesis doc.

---

## Coordinator Phases

```
PHASE 1 — Explore
  For each similarity axis:
    a. Allocate task_id, append pending row to manifest.
    b. Dispatch movie-explorer via Agent tool.
    c. Call record_findings with returned JSON.
    d. Verify manifest row flipped to complete; else mark failed.

PHASE 2 — Evaluate
  Call evaluate_coverage (score 0-10, gaps, sufficient bool).

PHASE 3 — Fill gaps (max 2 rounds)
  If sufficient=false, dispatch more movie-explorer calls for gap axes.

PHASE 4 — Synthesize
  Dispatch movie-synthesizer with all complete scratchpad paths.

PHASE 5 — Complete
  Call submit_complete with synthesis doc path.
```

---

## File Layout

```
findings-with-synthesis/
  .claude/agents/
    movie-explorer.md          # exploration subagent definition
    movie-synthesizer.md       # synthesis subagent definition
  FINDINGS/
    <task_id>-<slug>.md        # one per explorer task
    _synthesis/
      <topic>.md               # consolidated synthesis docs
  manifest.json                # task state registry
  main.py                      # upgraded coordinator
  coordinator.py               # reconcile / verify / stuck helper (ported from doom-explore)
  PLAN.md
  SPEC.md
```

---

## Task Breakdown

### T1 — Scaffold directories & manifest
- Create `FINDINGS/` and `FINDINGS/_synthesis/` with `.gitkeep`.
- Create `manifest.json` with `{ "version": 1, "tasks": [] }`.

### T2 — Author `movie-explorer` agent
- `.claude/agents/movie-explorer.md` with frontmatter: `name`, `description`, `tools: WebSearch, WebFetch, Read, Write, Edit`, `model: claude-haiku-4-5-20251001`.
- Embed scratchpad format contract + manifest update rules + provenance requirements (every finding must include a real fetched URL and verbatim quote; agent_output is not a valid source).

### T3 — Author `movie-synthesizer` agent
- `.claude/agents/movie-synthesizer.md` with frontmatter: `tools: Read, Glob`.
- Embed synthesis doc format + requirement to preserve all claim→source mappings + conflict annotation rules + temporal note rules.
- Hard constraint: must never read from outside `FINDINGS/`.

### T4 — Upgrade `main.py`
- Replace current single-agent loop with coordinator phases (T1–T5 above).
- Keep existing `FindingItem`, `FindingSource`, `FindingList`, `Finding` Pydantic models unchanged.
- Add MCP tools: `record_findings` (existing), `evaluate_coverage` (existing), `submit_complete` (existing).
- Add manifest read/write helpers.
- Add `Agent` tool dispatch for both subagent kinds.

### T5 — Port `coordinator.py`
- Copy reconcile / verify / stuck logic from doom-explore; swap path references to this project.

### T6 — Resume flow
- On startup, scan manifest for `running`/`failed` rows.
- Re-dispatch with `resume_from` pointing at existing scratchpad path.
- Subagent appends; never overwrites prior sections.

### T7 — Smoke test
- Run with the existing "School in the Crosshairs" question.
- Verify synthesis doc cites scratchpads, contains a conflict table (even if empty), and temporal notes section.
- Verify parent coordinator never held raw film-list text in its own context.

---

## Acceptance Criteria

- Every `FindingItem` in every scratchpad has a populated `source` with `published_at` and `accessed_at`.
- `movie-synthesizer` produces a Claim–Source Map table with no orphaned claims.
- Conflicting facts from different scratchpads appear in the Conflicts Retained table rather than being silently merged.
- Killing and restarting the coordinator mid-run resumes without losing prior scratchpad content.
- `movie-synthesizer` has no `Grep` tool and never reads outside `FINDINGS/`.
- Parent `main.py` never holds raw per-film research text — only IDs, paths, and summary strings.
