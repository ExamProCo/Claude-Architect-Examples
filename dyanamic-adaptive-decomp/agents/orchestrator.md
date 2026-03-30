# OrchestratorAgent — System Prompt (Documentation)

This file documents the OrchestratorAgent's role in the Dynamic Adaptive Decomposition (DAD) system. The orchestrator is implemented in code (`src/orchestrator.ts`) rather than being invoked as an LLM agent directly. This file serves as architectural documentation.

## Role

The OrchestratorAgent is the central coordinator of the world generation pipeline. It:

1. Receives a player action (move, examine, interact, attack)
2. Determines which sub-agents need to be invoked and in what order
3. Passes each agent's output to the next agent as input
4. Maintains the world state across all agent calls
5. Decides when generation is complete

## DAD Decision Tree

```
PlayerAction: move to unknown room
  → RoomBuilderAgent → RoomBlueprint
      → [if npcSlots.length > 0] NPCAgent × N (parallel)
          → [if npc.isCombatant] CombatAgent (per combatant NPC)
          → [if npc.isQuestGiver] QuestAgent (recursive, depth-capped)
      → [if features includes "puzzle"] PuzzleAgent
      → CodeWriterAgent × M (all artifacts, parallel)
      → LoreAgent × M (all artifacts, parallel)
      → LoreConsistencyAgent (once, with circuit breaker)
          → [if !consistent] LoreAgent × P (patch targets only)
  → WorldState persisted
  → GameResponse returned to player
```

## Stopping Conditions

| Phase | Stops When |
|---|---|
| Room generation | generationStatus === "complete" |
| Quest expansion | currentDepth >= maxDepth OR hasOpenBranches === false |
| Lore consistency | consistent === true OR iteration count >= 3 |
| Overall turn | openBranches.length === 0 |

## World State Invariants

The orchestrator guarantees:
- No room is returned to the player with generationStatus !== "complete"
- Every NPC in room.npcSlots has a corresponding entry in worldState.npcs
- Every lore entry's consistencyFlags are registered in worldState.consistencyFlags
- The decompositionLog records every agent call made during a turn
- Failed agent calls produce fallback data rather than crashing generation

## Agent Token Budgets

| Agent | max_tokens |
|---|---|
| orchestrator | 2048 |
| room-builder | 1024 |
| npc | 1024 |
| quest | 1024 |
| lore | 512 |
| lore-consistency | 1024 |
| code-writer | 2048 |
| combat | 1536 |
| puzzle | 1536 |

## Key Files

- `src/orchestrator.ts`: The implementation of this agent's logic
- `src/branch-resolver.ts`: Manages the BranchTask queue and parallel resolution
- `src/agent-runner.ts`: Invokes individual agent markdown files via the Claude API
- `src/world-state.ts`: Read/write operations for world-state.json
