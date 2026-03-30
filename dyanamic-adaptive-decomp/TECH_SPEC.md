# TECH_SPEC.md — Agent Dungeon: Dynamic Adaptive Decomposition

## 1. Executive Summary

The Agent Dungeon is a text-based game where the world does not exist until the player explores it. A Claude-powered agent system must construct that world incrementally, in code, as each player action demands new content. Static pre-planning is architecturally impossible: the number of rooms, their connections, their inhabitants, and their narrative significance all depend on decisions the player has not yet made.

Dynamic Adaptive Decomposition (DAD) is not an optimization choice here — it is the only viable pattern. The branching factor is player-driven, the depth is unbounded, and every intermediate output (a room description, an item found, a door opened) must change which agent runs next, with what instructions, and whether to spawn deeper sub-tasks or declare a branch complete.

---

## 2. Generation Boundary — What AI Controls vs. What Code Controls

The AI agents power **world generation only**. The game engine is pure code.

**Game Engine (code, no AI):**
- Player movement and navigation
- Combat resolution (turn logic, damage, death)
- Inventory management
- Quest state tracking (flags, completion checks)
- All game rules and mechanics

**World Generator (AI agents):**
- Fires **only** when the player moves into a room that does not yet exist in `world-state.json`
- Generates the room, NPCs, items, lore, and TypeScript code — once
- After generation, that room is permanent static data; AI never touches it again

```typescript
// main.ts — the game engine
async function handleMove(direction: Direction) {
  const targetId = currentRoom.exits[direction];

  // Only trigger AI if room has never been visited
  if (!worldState.rooms[targetId]) {
    await orchestrator.generateRoom(targetId, worldState);
  }

  // From here: pure code, no AI
  currentRoom = worldState.rooms[targetId];
  renderRoom(currentRoom);
}
```

The entire `RoomBlueprint → NPC → Quest → Code → Lore` chain runs inside that single `generateRoom()` call. Once it resolves, the room is treated identically to any hand-authored room — the game engine drives everything from that point forward.

---

## 3. Where DAD Is Genuinely Required (Not Optional)

### 2.1 Unknown Branching at Room Generation Time

When the player moves North, the orchestrator does not know whether the next room is a dead end, a branching junction with 4 exits, a boss chamber requiring narrative setup, or an environmental puzzle requiring custom code generation. The number of sub-tasks (exits to generate, NPCs to instantiate, items to place, lore to produce) cannot be determined before inspecting the generated room's structural properties.

**Why static planning fails here:** A pre-planned graph of "generate 5 rooms" produces a flat, context-free world. The generator cannot know that the player is 3 levels deep in a necromancer's tower and that the next room should escalate tension, not reset it.

### 2.2 NPC Encounter Depth Is Non-Deterministic

An NPC can be: ignorable (1 agent call — flavor text), interactive (3-5 calls — dialogue tree generation), quest-giving (8-12 calls — quest state, reward item generation, world state mutation), or a mini-boss (N calls — combat system generation, loot table, defeat narrative). The NPC's role is determined by the orchestrator reading the current world state and narrative context, not by a fixed script.

**Why static planning fails here:** You cannot enumerate NPC interaction depth upfront without knowing who the player has met, what quests are active, what zone depth they're at, or what narrative threads need resolving.

### 2.3 Code Generation for World Artifacts Has Unknown Scope

The game world is realized as TypeScript code: Room classes, Item interfaces, NPC behavior objects, puzzle validators. When a room is generated, the agent must decide whether it requires: a simple data object (1 call), a class with methods (3-4 calls), a stateful puzzle module (6-10 calls including validation logic), or a combat encounter module (8-15 calls including turn logic). This decision can only be made after seeing the room's structural description.

**Why static planning fails here:** A fixed "generate room code" task cannot anticipate that the room contains a pressure-plate puzzle requiring a custom `PuzzleSolver` class with `validate()`, `hint()`, and `reset()` methods that must reference specific room-state variables.

### 2.4 Narrative Consistency Requires Retroactive Branching

When the player finds a mysterious key in room 7, the orchestrator may need to retroactively place a locked door somewhere in already-generated rooms, and then regenerate the lore for 2-3 rooms to make the key's provenance coherent. The number of rooms that require lore patching is unknown until the LoreConsistencyAgent inspects the existing world state graph.

**Why static planning fails here:** No pre-plan can predict which previously-generated rooms need retroactive modification based on a newly-placed artifact.

### 2.5 Quest Thread Depth Is Player-Driven

A quest starts as a single breadcrumb. As the player follows it, each clue discovered may spawn 0, 1, or N sub-quests. A side quest about a missing merchant may unfold into a 2-step fetch quest or a 15-step conspiracy spanning 8 rooms with 4 named NPCs and a custom ending. The orchestrator cannot know the quest's ultimate shape until the player's choices have been made.

---

## 4. DAD Concept Mapping

| Game Concept | DAD Concept |
|---|---|
| Player action (move, interact, examine) | Trigger that initiates a decomposition cycle |
| World generation for a new room | Top-level task |
| Room sub-features (exits, NPCs, items, lore) | Sub-tasks, spawned dynamically based on room structure |
| "Does this room need a puzzle?" | Conditional branch decision made mid-execution |
| Room code written to `/world/rooms/` | Intermediate artifact that changes downstream agent behavior |
| World state graph in `world-state.json` | Shared context passed between all agents |
| "No more exits to generate" | Stopping condition for a branch |
| Quest thread completion | Stopping condition for a task tree |
| Narrative inconsistency detected | Triggers a retroactive re-decomposition cycle |

---

## 5. Agent Architecture

### 4.1 Agent Inventory

All agents live as prompt files in `/agents/`. Each is invoked by the orchestrator via the Claude Agent SDK's filesystem agent pattern.

**`/agents/orchestrator.md`** — OrchestratorAgent

The central coordinator and the only agent that maintains the full decomposition state. It reads the current `world-state.json`, receives a player action, decides which agents to call and in what sequence, interprets their outputs, and decides whether to branch deeper, spawn parallel sub-tasks, or declare completion. This is the DAD engine. It does not generate content itself.

Decision logic the orchestrator makes at runtime:
- Is this room structurally simple (1-2 exits, no special features) → call RoomBuilderAgent only
- Does the room have an NPC → after RoomBuilderAgent completes, call NPCAgent
- Does the NPC have a quest flag → after NPCAgent completes, call QuestAgent
- Does QuestAgent return `questDepth > 2` → spawn additional LoreAgent calls for each quest node
- Has the world state graph gained a new artifact type not seen before → call CodeSchemaAgent to generate a new TypeScript interface
- Has the lore consistency score dropped below threshold → call LoreConsistencyAgent before returning to player

**`/agents/room-builder.md`** — RoomBuilderAgent

Takes: `{ zone: string, depth: number, worldState: WorldStateSnapshot, playerHistory: string[] }`

Generates the room's structural description: exits (direction + type), atmosphere, environmental features, initial item placements, NPC slots. Critically, it outputs a `RoomBlueprint` object, not final code. The blueprint's contents determine which agents the orchestrator calls next.

Returns: `RoomBlueprint`

**`/agents/npc.md`** — NPCAgent

Takes: `{ npcSlot: NPCSlot, roomContext: RoomBlueprint, worldState: WorldStateSnapshot }`

Determines NPC type, generates dialogue tree skeleton, assigns behavioral flags (`isQuestGiver`, `isCombatant`, `isInformant`), and produces the NPC's TypeScript class definition. If `isQuestGiver: true`, it returns a `QuestSeed` in its output, which the orchestrator uses to decide whether to invoke QuestAgent.

Returns: `NPCDefinition & { questSeed?: QuestSeed }`

**`/agents/quest.md`** — QuestAgent

Takes: `{ questSeed: QuestSeed, worldState: WorldStateSnapshot, currentDepth: number, maxDepth: number }`

Decides quest structure: linear (depth 1-2), branching (depth 3-5), or epic (depth 6+). Generates quest nodes incrementally — each node returned causes the orchestrator to call QuestAgent again for each unresolved branch node, unless `currentDepth >= maxDepth` or the quest reaches a natural terminus. This is DAD's recursive pattern made explicit.

Returns: `QuestNode[] & { hasOpenBranches: boolean, suggestedNextNodes: QuestNodeSeed[] }`

**`/agents/lore.md`** — LoreAgent

Takes: `{ target: Room | NPC | Item | Quest, worldState: WorldStateSnapshot, consistencyContext: string[] }`

Generates narrative text for a single target. It does not decide what to generate — it only generates for what it is given. However, it returns `consistencyFlags: string[]` — named world facts this lore entry depends on (e.g., `"king-is-dead"`, `"merchant-missing"`). The orchestrator logs these flags and uses them to detect when new content would contradict existing lore.

Returns: `LoreEntry & { consistencyFlags: string[] }`

**`/agents/code-writer.md`** — CodeWriterAgent

Takes: `{ blueprint: RoomBlueprint | NPCDefinition | QuestNode | ItemDefinition, existingTypes: TypeRegistry }`

Produces TypeScript code for a single game artifact. Checks the `TypeRegistry` to avoid re-declaring existing interfaces. Determines internally whether the artifact needs a plain data object, a class, or a module with multiple exported functions. Returns both the code string and a `TypeRegistryPatch` declaring any new types it introduced.

Returns: `{ code: string, filePath: string, typeRegistryPatch: TypeRegistryPatch }`

**`/agents/lore-consistency.md`** — LoreConsistencyAgent

Takes: `{ worldState: WorldStateSnapshot, newEntries: LoreEntry[], affectedRoomIds: string[] }`

Scans the world state for contradictions between new lore entries and existing consistency flags. Returns a list of `PatchTarget` objects — rooms, NPCs, or items that need their lore regenerated. The orchestrator then spawns new LoreAgent calls for each PatchTarget. This is the retroactive re-decomposition path.

Returns: `{ consistent: boolean, patchTargets: PatchTarget[] }`

**`/agents/combat.md`** — CombatAgent

Takes: `{ combatantNPC: NPCDefinition, playerStats: PlayerStats, roomContext: RoomBlueprint }`

Generates turn-based combat logic for a specific encounter. Only invoked if `NPCDefinition.isCombatant === true`. Returns a `CombatModule` containing attack patterns, defeat conditions, loot table, and the TypeScript implementation. Because combat depth (number of phases, special mechanics) is unknown until the NPC's power level and room type are analyzed, this agent may invoke itself recursively via the orchestrator for multi-phase bosses.

Returns: `CombatModule & { hasPhases: boolean, phaseSeeds?: CombatPhaseSeed[] }`

**`/agents/puzzle.md`** — PuzzleAgent

Takes: `{ roomBlueprint: RoomBlueprint, puzzleType: string, worldState: WorldStateSnapshot }`

Only invoked when `RoomBlueprint.features` contains a puzzle slot. Generates puzzle logic: win condition, hint system, reset behavior, and TypeScript validator code. The puzzle's complexity (number of steps, whether it has sub-puzzles) is determined by zone depth and player progress, making it unknown at orchestration time.

Returns: `PuzzleDefinition & { subPuzzles?: PuzzleSeed[] }`

---

## 6. World State Model

The world state is the shared artifact that makes DAD coherent across agent calls. Every agent receives a snapshot; only the orchestrator writes to it.

### 5.1 `world-state.json` Shape

```typescript
interface WorldState {
  meta: {
    sessionId: string;
    playerName: string;
    currentRoomId: string;
    turnCount: number;
    generatedAt: string;
  };

  rooms: Record<string, Room>;
  npcs: Record<string, NPCDefinition>;
  items: Record<string, ItemDefinition>;
  quests: Record<string, QuestNode[]>;
  loreEntries: Record<string, LoreEntry>;

  consistencyFlags: Record<string, boolean>;   // named world facts
  typeRegistry: TypeRegistry;                   // all generated TS types/interfaces

  decompositionLog: DecompositionEntry[];       // audit trail of agent calls
  openBranches: BranchTask[];                   // tasks pending resolution
}
```

### 5.2 Key Sub-types

```typescript
interface Room {
  id: string;
  zone: string;
  depth: number;
  exits: Record<Direction, ExitDescriptor | null>;
  npcSlots: string[];         // NPC ids
  itemSlots: string[];        // item ids
  features: RoomFeature[];    // "puzzle", "trap", "shrine", etc.
  codeFile: string;           // path to generated .ts file
  loreEntryId: string;
  generationStatus: "blueprint" | "coded" | "lored" | "complete";
}

interface RoomBlueprint {
  structuralDescription: string;
  exits: ExitDescriptor[];
  npcSlots: NPCSlot[];
  itemSlots: ItemSlot[];
  features: RoomFeature[];
  atmosphereHints: string[];
  narrativeWeight: "low" | "medium" | "high" | "climactic";
}

interface BranchTask {
  id: string;
  type: "room" | "npc" | "quest" | "lore" | "code" | "puzzle" | "combat";
  agentName: string;
  input: Record<string, unknown>;
  dependsOn: string[];        // other BranchTask ids that must complete first
  status: "pending" | "running" | "complete" | "blocked";
  depth: number;              // how deep in the decomposition tree this task sits
}

interface DecompositionEntry {
  turnId: string;
  agentCalled: string;
  inputSummary: string;
  outputSummary: string;
  branchesSpawned: string[];  // BranchTask ids created by this call
  branchesClosed: string[];   // BranchTask ids this call resolved
  timestamp: string;
}

interface TypeRegistry {
  interfaces: Record<string, string>;   // name → TS source
  classes: Record<string, string>;
  modules: Record<string, string>;
}
```

### 5.3 Incremental Build-up

Each player turn starts with `openBranches: []`. The orchestrator adds branches as it discovers them. It resolves them in dependency order. A turn is complete when `openBranches` is empty AND the room the player moved to has `generationStatus: "complete"`. Partial state (e.g., room is `"blueprint"` status) is valid mid-turn but never returned to the player.

---

## 7. Orchestrator Decision Logic (Pseudo-code)

```typescript
async function handlePlayerAction(action: PlayerAction, worldState: WorldState): Promise<GameResponse> {
  const branches: BranchTask[] = [];

  // Phase 1: Room needs to exist
  if (action.type === "move" && !worldState.rooms[action.targetRoomId]) {
    branches.push({ type: "room", agentName: "room-builder", ... });
  }

  // Phase 2: Process RoomBlueprint outputs to discover what's needed
  const blueprint = await resolveRoomBlueprint(branches[0], worldState);

  if (blueprint.npcSlots.length > 0) {
    for (const slot of blueprint.npcSlots) {
      branches.push({ type: "npc", agentName: "npc", dependsOn: ["room"], ... });
    }
  }

  if (blueprint.features.includes("puzzle")) {
    branches.push({ type: "puzzle", agentName: "puzzle", dependsOn: ["room"], ... });
  }

  // Phase 3: Process NPC outputs to discover deeper needs
  const npcResults = await resolveParallel(branches.filter(b => b.type === "npc"), worldState);

  for (const npc of npcResults) {
    if (npc.isCombatant) {
      branches.push({ type: "combat", agentName: "combat", dependsOn: [npc.id], ... });
    }
    if (npc.questSeed) {
      branches.push({ type: "quest", agentName: "quest", dependsOn: [npc.id], ... });
    }
  }

  // Phase 4: Quest recursion — keep expanding until no open branches remain
  let questBranches = branches.filter(b => b.type === "quest");
  while (questBranches.some(b => b.status !== "complete")) {
    const result = await resolveQuestBranch(questBranches, worldState);
    if (result.hasOpenBranches && result.currentDepth < MAX_QUEST_DEPTH) {
      for (const seed of result.suggestedNextNodes) {
        branches.push({ type: "quest", agentName: "quest", dependsOn: [...], depth: result.currentDepth + 1 });
      }
    }
    questBranches = branches.filter(b => b.type === "quest" && b.status !== "complete");
  }

  // Phase 5: Generate all code
  const codeTargets = [...rooms, ...npcs, ...puzzles, ...combatModules];
  for (const target of codeTargets) {
    branches.push({ type: "code", agentName: "code-writer", dependsOn: [target.id], ... });
  }

  // Phase 6: Generate lore for all entities
  const loreTargets = codeTargets;
  const loreEntries = await resolveParallel(loreTargets.map(t => ({ type: "lore", ... })));

  // Phase 7: Consistency check — may spawn retroactive patches
  const consistencyResult = await callAgent("lore-consistency", { worldState, newEntries: loreEntries });
  if (!consistencyResult.consistent) {
    for (const patch of consistencyResult.patchTargets) {
      // Retroactive re-decomposition: lore branches re-opened
      branches.push({ type: "lore", agentName: "lore", dependsOn: [], input: { target: patch } });
    }
    await resolveParallel(patchBranches);
  }

  // Phase 8: Persist and return
  await writeWorldState(worldState);
  await writeGeneratedCode(branches);
  return buildPlayerResponse(worldState, action);
}
```

---

## 8. File System Layout

```
/
├── src/
│   ├── main.ts                  # Game loop + player I/O
│   ├── orchestrator.ts          # OrchestratorAgent driver (DAD engine)
│   ├── agent-runner.ts          # Invokes /agents/*.md via Claude Agent SDK
│   ├── world-state.ts           # WorldState read/write, snapshot helpers
│   ├── branch-resolver.ts       # BranchTask queue, dependency ordering
│   └── types.ts                 # All shared TypeScript interfaces
│
├── agents/
│   ├── orchestrator.md          # Orchestrator system prompt
│   ├── room-builder.md
│   ├── npc.md
│   ├── quest.md
│   ├── lore.md
│   ├── lore-consistency.md
│   ├── code-writer.md
│   ├── combat.md
│   └── puzzle.md
│
├── world/
│   ├── world-state.json         # Live world state (grows each turn)
│   ├── rooms/                   # Generated room .ts files
│   ├── npcs/                    # Generated NPC .ts files
│   ├── quests/                  # Generated quest .ts files
│   ├── items/                   # Generated item .ts files
│   └── modules/                 # Generated puzzle/combat .ts files
│
└── package.json
```

---

## 9. Where Static Pre-Planning Fails Specifically

### 8.1 You Cannot Pre-Generate the Dungeon Graph

A static dungeon generator creates a finite graph before play begins. The problem: a player who never goes East never needs the Eastern wing. Every room pre-generated is wasted compute and token budget. With DAD, zero rooms exist until the player moves toward them. The world is as large as the player makes it.

### 8.2 You Cannot Pre-Assign NPC Roles

A static system assigns NPC types at dungeon creation time. If the player ignores 80% of NPCs, 80% of quest generation was wasted. Worse: static assignment cannot make an NPC quest-relevant based on what the player has already done (e.g., an NPC becomes a quest-giver only because the player already found the artifact they're looking for). DAD resolves NPC depth on demand, informed by current world state.

### 8.3 You Cannot Pre-Generate TypeScript Code for Unknown Structures

The game world is realized in code. A pre-plan would require knowing every Room subclass, every NPC behavior pattern, every puzzle validator before any of them exist. CodeWriterAgent only generates what the world state has actually demanded, referencing only the types that have been registered. A static approach would produce a massive, mostly-wrong type system up front.

### 8.4 Lore Consistency Cannot Be Guaranteed Statically

Static lore is written before player choices are made. If the player takes an unexpected path, pre-written lore about "the sealed Eastern gate" becomes incoherent when the player walked through it 10 turns ago. The LoreConsistencyAgent, triggered only when new lore contradicts existing `consistencyFlags`, patches retroactively. A static system has no mechanism for this.

### 8.5 Quest Depth Is a Player-Determined Variable

A player who never talks to NPCs has depth-0 quests. A player who exhausts every dialogue option has depth-10 quests. Pre-planning forces a choice: generate depth-10 quests for every NPC (wasteful, creates a rigid world) or cap at depth-2 (produces a shallow game). DAD generates exactly as deep as the player goes, and no deeper.

---

## 10. Stopping Conditions

Each agent type has explicit stopping conditions to prevent infinite decomposition.

| Agent | Stops When |
|---|---|
| OrchestratorAgent | `openBranches.length === 0` AND room is `"complete"` |
| QuestAgent | `currentDepth >= maxDepth` OR `hasOpenBranches === false` OR quest reaches a terminal node type |
| CombatAgent | `hasPhases === false` OR `phaseCount >= MAX_COMBAT_PHASES (3)` |
| PuzzleAgent | `subPuzzles` is empty OR `puzzleDepth >= 2` |
| LoreConsistencyAgent | `patchTargets.length === 0` OR patch loop count exceeds 3 (circuit breaker) |
| LoreAgent | Always single-call (generates one entry per invocation, no recursion) |
| CodeWriterAgent | Always single-call (generates one artifact per invocation, no recursion) |

---

## 11. Data Contracts Between Agents

The orchestrator is the only component that passes data between agents. Agents never call other agents. All inter-agent communication flows through the orchestrator's interpretation of output and construction of next-call input.

```
PlayerAction
    → OrchestratorAgent (reads WorldState)
        → RoomBuilderAgent → RoomBlueprint
            → [conditional] NPCAgent × N → NPCDefinition[]
                → [conditional] QuestAgent (recursive via orchestrator) → QuestNode[]
                → [conditional] CombatAgent → CombatModule
            → [conditional] PuzzleAgent → PuzzleDefinition
        → CodeWriterAgent × M → { code, typeRegistryPatch }[]
        → LoreAgent × M → LoreEntry[]
        → LoreConsistencyAgent → { consistent, patchTargets }
            → [conditional] LoreAgent × P (patch calls)
    → WorldState (persisted)
    → GameResponse (returned to player)
```

---

## 12. Model Configuration

All agents use `claude-haiku-4-5-20251001`. Token budgets per agent call:

| Agent | max_tokens | Rationale |
|---|---|---|
| OrchestratorAgent | 2048 | Needs to reason about branching decisions |
| RoomBuilderAgent | 1024 | Structured blueprint, not prose |
| NPCAgent | 1024 | Character definition + class code |
| QuestAgent | 1024 | Per-node, not full quest at once |
| LoreAgent | 512 | Short narrative prose only |
| LoreConsistencyAgent | 1024 | Needs to scan and reason about flags |
| CodeWriterAgent | 2048 | TypeScript code gen may be verbose |
| CombatAgent | 1536 | Combat module with multiple methods |
| PuzzleAgent | 1536 | Puzzle logic + validator code |

---

## 13. Implementation Phases

**Phase 1 — Skeleton (turns work, world doesn't persist)**
- `main.ts` game loop with stubbed rooms
- `orchestrator.ts` with hardcoded 2-agent pipeline (OrchestratorAgent → RoomBuilderAgent)
- `world-state.ts` read/write
- Basic `/agents/room-builder.md` prompt

**Phase 2 — Core DAD Loop**
- `branch-resolver.ts` with dependency ordering
- NPCAgent + conditional invocation from orchestrator
- CodeWriterAgent + `TypeRegistry` tracking
- World persists between turns (`world-state.json` grows)

**Phase 3 — Deep Decomposition**
- QuestAgent recursive loop with depth cap
- CombatAgent with phase detection
- PuzzleAgent with sub-puzzle branching

**Phase 4 — Consistency and Retroactive Patching**
- LoreAgent for all entity types
- LoreConsistencyAgent with patch loop
- Circuit breaker on patch recursion depth

**Phase 5 — Player-Facing Game**
- Formatted player output from `world-state.json`
- Save/load session
- Turn history display

---

## 14. Critical Files for Implementation

- `src/orchestrator.ts` — the DAD engine; every branching decision, agent invocation sequence, stopping condition, and world-state mutation lives here; highest-leverage file in the system
- `src/branch-resolver.ts` — manages the `BranchTask[]` queue, topological dependency ordering, and parallel vs. sequential resolution logic that makes DAD work without deadlocking
- `src/types.ts` — defines `WorldState`, `RoomBlueprint`, `BranchTask`, `TypeRegistry`, and all inter-agent data contracts; every agent prompt and every orchestrator branch decision depends on these shapes being correct
- `agents/orchestrator.md` — the system prompt that teaches the LLM to read intermediate outputs and decide what to spawn next; encodes the entire DAD routing logic in natural language and is the primary control surface for tuning world generation behavior
