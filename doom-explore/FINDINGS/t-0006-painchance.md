# t-0006: How is painchance computed when a monster or player is hit?

## Question
What mechanism governs whether a hit triggers pain state, and where is painchance set per mobj type?

## Entry points
- `linuxdoom-1.10/p_inter.c:855` — `P_DamageMobj` contains the painchance roll (partial read; crashed before tracing further)

## Call chain
1. `P_DamageMobj` (`p_inter.c:775`) — receives damage
2. Painchance roll at `p_inter.c:894` — P_Random() < target->info->painchance
3. `P_SetMobjState` (`p_mobj.c:54`) — transitions to pain state if roll succeeds
4. State machine (`p_mobj.c:70-81`) — sets sprite, tics, and triggers action functions

## Update 2026-04-18T21:30:00Z

### Completed Investigation

**Painchance Definition (per mobj_t type):**
- Field defined in `info.h:1315` as `int painchance`
- Instantiated per-type in `info.c` (e.g., `255` for players at `info.c:1117`, `200` for Zombieman at `info.c:1143`)
- Represents probability (0-255) that hit triggers pain state

**Roll Mechanism in P_DamageMobj:**
- `p_inter.c:894` compares: `P_Random() < target->info->painchance`
- Also checks `!(target->flags&MF_SKULLFLY)` — pain disabled if already attacking
- On success, sets `MF_JUSTHIT` flag and calls `P_SetMobjState(target, target->info->painstate)` at `p_inter.c:899`

**Pain State Transition:**
- `P_SetMobjState` (`p_mobj.c:54-84`) transitions mobj to pain state
- Copies state fields: sprite, frame, tics; executes action function if present
- Returns to caller; pain animation continues until next state

### Key Files
- `linuxdoom-1.10/info.h:1315` — painchance field in mobjinfo_t
- `linuxdoom-1.10/info.c:1117+` — per-type painchance values
- `linuxdoom-1.10/p_inter.c:894-900` — painchance roll and state transition
- `linuxdoom-1.10/p_mobj.c:54-84` — P_SetMobjState implementation

### Open follow-ups
- What pain state animations exist per mobj type?
- How do pain sounds trigger relative to state transitions?
