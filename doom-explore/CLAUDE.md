# doom-explore

Exploration orchestrator over the DOOM codebase in `doom-src/`. Design in
`SPEC.md`.

**When coordinating exploration work in this directory, use the
`doom-coordinator` skill.** It handles session-start reconciliation,
pre-dispatch manifest updates, post-dispatch verification, and resume flow.

Never Read or Grep `doom-src/` from the parent agent — that's the
`doom-explorer` subagent's job. Doing it yourself defeats the
context-isolation design.
