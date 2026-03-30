import {
  WorldState,
  Room,
  RoomBlueprint,
  NPCDefinition,
  QuestNode,
  LoreEntry,
  BranchTask,
  DecompositionEntry,
  PlayerAction,
  GameResponse,
  Direction,
  ExitDescriptor,
  PuzzleDefinition,
  PatchTarget,
} from './types';
import { callAgent } from './agent-runner';
import { resolveParallel, getMaxTokensForAgent } from './branch-resolver';
import { saveWorldState } from './world-state';

// ============================================================
// Constants
// ============================================================

const MAX_QUEST_DEPTH = 3;
const MAX_LORE_PATCH_ITERATIONS = 3;

// ============================================================
// Helpers
// ============================================================

function makeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function makeBranchTask(
  type: BranchTask['type'],
  agentName: string,
  input: Record<string, unknown>,
  dependsOn: string[] = [],
  depth = 0
): BranchTask {
  return {
    id: `${type}_${makeId()}`,
    type,
    agentName,
    input,
    dependsOn,
    status: 'pending',
    depth,
  };
}

function logDecomposition(
  worldState: WorldState,
  entry: Omit<DecompositionEntry, 'timestamp'>
): void {
  worldState.decompositionLog.push({ ...entry, timestamp: new Date().toISOString() });
}

// Safe cast helpers — coerce unknown agent output into typed shapes
function asBlueprint(raw: unknown): RoomBlueprint | null {
  if (raw === null || typeof raw !== 'object') return null;
  const r = raw as Partial<RoomBlueprint>;
  if (!r.structuralDescription) return null;
  return {
    structuralDescription: String(r.structuralDescription),
    title: r.title ? String(r.title) : undefined,
    exits: Array.isArray(r.exits) ? (r.exits as ExitDescriptor[]) : [],
    npcSlots: Array.isArray(r.npcSlots) ? r.npcSlots : [],
    itemSlots: Array.isArray(r.itemSlots) ? r.itemSlots : [],
    features: Array.isArray(r.features) ? r.features : [],
    atmosphereHints: Array.isArray(r.atmosphereHints) ? r.atmosphereHints : [],
    narrativeWeight:
      (['low', 'medium', 'high', 'climactic'] as const).includes(
        r.narrativeWeight as 'low' | 'medium' | 'high' | 'climactic'
      )
        ? (r.narrativeWeight as RoomBlueprint['narrativeWeight'])
        : 'low',
  };
}

function asNPC(raw: unknown): NPCDefinition | null {
  if (raw === null || typeof raw !== 'object') return null;
  const r = raw as Partial<NPCDefinition>;
  if (!r.id || !r.name) return null;
  return {
    id: String(r.id),
    name: String(r.name),
    type: r.type ?? 'neutral',
    description: String(r.description ?? ''),
    dialogueTree: (r.dialogueTree as Record<string, string>) ?? {},
    behaviorFlags: {
      isQuestGiver: r.behaviorFlags?.isQuestGiver ?? false,
      isCombatant: r.behaviorFlags?.isCombatant ?? false,
      isInformant: r.behaviorFlags?.isInformant ?? false,
    },
    stats: {
      hp: r.stats?.hp ?? 20,
      attack: r.stats?.attack ?? 3,
      defense: r.stats?.defense ?? 1,
      level: r.stats?.level ?? 1,
    },
    questSeed: r.questSeed,
  };
}

function asQuestNodes(raw: unknown): { nodes: QuestNode[]; hasOpenBranches: boolean; seeds: unknown[] } {
  const empty = { nodes: [], hasOpenBranches: false, seeds: [] };
  if (raw === null || typeof raw !== 'object') return empty;
  const r = raw as Record<string, unknown>;
  return {
    nodes: Array.isArray(r.questNodes) ? (r.questNodes as QuestNode[]) : [],
    hasOpenBranches: Boolean(r.hasOpenBranches),
    seeds: Array.isArray(r.suggestedNextNodes) ? r.suggestedNextNodes : [],
  };
}

function asLoreEntry(raw: unknown, fallbackTargetId: string, fallbackType: LoreEntry['targetType']): LoreEntry | null {
  if (raw === null || typeof raw !== 'object') return null;
  const r = raw as Partial<LoreEntry>;
  return {
    id: r.id ? String(r.id) : `lore_${makeId()}`,
    targetId: r.targetId ? String(r.targetId) : fallbackTargetId,
    targetType: r.targetType ?? fallbackType,
    text: r.text ? String(r.text) : 'A place shrouded in mystery.',
    consistencyFlags: Array.isArray(r.consistencyFlags) ? r.consistencyFlags : [],
  };
}

interface RawCombat {
  npcId?: string;
  attackPatterns?: unknown[];
  defeatConditions?: unknown[];
  lootTable?: unknown[];
  phases?: number;
  hasPhases?: boolean;
  phaseSeeds?: unknown[];
}

function asCombat(raw: unknown, npcId: string): RawCombat | null {
  if (raw === null || typeof raw !== 'object') return null;
  const r = raw as RawCombat;
  return {
    npcId: r.npcId ? String(r.npcId) : npcId,
    attackPatterns: Array.isArray(r.attackPatterns) ? r.attackPatterns : [],
    defeatConditions: Array.isArray(r.defeatConditions) ? r.defeatConditions : ['Reduce HP to 0'],
    lootTable: Array.isArray(r.lootTable) ? r.lootTable : [],
    phases: typeof r.phases === 'number' ? r.phases : 1,
    hasPhases: Boolean(r.hasPhases),
    phaseSeeds: Array.isArray(r.phaseSeeds) ? r.phaseSeeds : [],
  };
}

function asPuzzle(raw: unknown): PuzzleDefinition | null {
  if (raw === null || typeof raw !== 'object') return null;
  const r = raw as Partial<PuzzleDefinition>;
  if (!r.id) return null;
  return {
    id: String(r.id),
    description: String(r.description ?? ''),
    winCondition: String(r.winCondition ?? ''),
    hints: Array.isArray(r.hints) ? r.hints : [],
    resetBehavior: r.resetBehavior ?? 'permanent',
    subPuzzles: Array.isArray(r.subPuzzles) ? r.subPuzzles : [],
  };
}

// Build a lightweight snapshot of worldState safe to pass to agents
function worldStateSnapshot(worldState: WorldState): Record<string, unknown> {
  return {
    meta: worldState.meta,
    consistencyFlags: worldState.consistencyFlags,
    roomIds: Object.keys(worldState.rooms),
    npcIds: Object.keys(worldState.npcs),
    questIds: Object.keys(worldState.quests),
    itemIds: Object.keys(worldState.items),
    recentLoreFlags: Object.values(worldState.loreEntries)
      .flatMap((l) => l.consistencyFlags)
      .slice(-20),
  };
}

// ============================================================
// Core generation pipeline
// ============================================================

export async function generateRoom(roomId: string, worldState: WorldState): Promise<void> {
  console.log(`[orchestrator] Generating room: ${roomId}`);

  // Derive zone and depth from roomId if possible
  // Format: room_{zone}_{depth}_{direction}   OR   entrance
  const parts = roomId.split('_');
  let zone = 'dungeon';
  let depth = 1;

  if (parts.length >= 3 && parts[0] === 'room') {
    zone = parts[1];
    depth = parseInt(parts[2], 10) || 1;
  }

  const turnId = makeId();

  // ---- Phase 1: Room Blueprint --------------------------------
  let blueprint: RoomBlueprint | null = null;
  try {
    const rawBlueprint = await callAgent(
      'room-builder',
      {
        roomId,
        zone,
        depth,
        worldState: worldStateSnapshot(worldState),
      },
      getMaxTokensForAgent('room-builder')
    );
    blueprint = asBlueprint(rawBlueprint);
  } catch (err) {
    console.error('[orchestrator] room-builder failed:', err);
  }

  // Fallback blueprint
  if (!blueprint) {
    blueprint = {
      structuralDescription: `A dimly lit chamber at depth ${depth}. The stone walls are cold and damp.`,
      exits: [
        {
          direction: Direction.south,
          type: 'open',
          targetRoomId: worldState.meta.currentRoomId,
          description: 'The way you came from.',
        },
      ],
      npcSlots: [],
      itemSlots: [],
      features: [],
      atmosphereHints: ['dark', 'silent'],
      narrativeWeight: 'low',
    };
  }

  logDecomposition(worldState, {
    turnId,
    agentCalled: 'room-builder',
    inputSummary: `roomId=${roomId} zone=${zone} depth=${depth}`,
    outputSummary: `blueprint: ${blueprint.narrativeWeight} weight, ${blueprint.npcSlots.length} NPCs, ${blueprint.exits.length} exits`,
    branchesSpawned: [],
    branchesClosed: [],
  });

  // Build the Room object from blueprint (generationStatus = "blueprint")
  const exitMap: Partial<Record<Direction, ExitDescriptor | null>> = {};
  for (const exit of blueprint.exits) {
    exitMap[exit.direction] = exit;
  }

  const room: Room = {
    id: roomId,
    zone,
    depth,
    title: blueprint.title,
    exits: exitMap,
    npcSlots: [],
    itemSlots: [],
    features: blueprint.features,
    codeFile: `world/rooms/${roomId}.ts`,
    loreEntryId: `lore_${roomId}`,
    generationStatus: 'blueprint',
  };
  worldState.rooms[roomId] = room;

  // ---- Phase 2: NPCs ------------------------------------------
  const npcTasks: BranchTask[] = blueprint.npcSlots.map((slot) =>
    makeBranchTask(
      'npc',
      'npc',
      { npcSlot: slot, roomContext: blueprint, worldState: worldStateSnapshot(worldState) },
      [],
      1
    )
  );

  // ---- Phase 2b: Puzzle (conditional) -------------------------
  const hasPuzzle = blueprint.features.includes('puzzle');
  let puzzleTask: BranchTask | null = null;
  if (hasPuzzle) {
    puzzleTask = makeBranchTask(
      'puzzle',
      'puzzle',
      { roomBlueprint: blueprint, puzzleType: 'environmental', worldState: worldStateSnapshot(worldState) },
      [],
      1
    );
  }

  // Run NPCs and puzzle in parallel
  const phase2Tasks = puzzleTask ? [...npcTasks, puzzleTask] : npcTasks;
  await resolveParallel(phase2Tasks, worldState);

  // Collect NPC results
  const npcResults: NPCDefinition[] = [];
  for (const task of npcTasks) {
    const npc = asNPC(task.result);
    if (npc) {
      worldState.npcs[npc.id] = npc;
      room.npcSlots.push(npc.id);
      npcResults.push(npc);
    }
  }

  // Collect puzzle result (stored in world state typeRegistry for future use)
  if (puzzleTask) {
    const puzzle: PuzzleDefinition | null = asPuzzle(puzzleTask.result);
    if (puzzle) {
      worldState.typeRegistry.modules[`puzzle_${puzzle.id}`] = JSON.stringify(puzzle);
    }
  }

  // ---- Phase 3: Per-NPC tasks (quest, combat) -----------------
  const questTasks: BranchTask[] = [];
  const combatTasks: BranchTask[] = [];

  for (const npc of npcResults) {
    if (npc.behaviorFlags.isCombatant) {
      combatTasks.push(
        makeBranchTask(
          'combat',
          'combat',
          {
            combatantNPC: npc,
            playerStats: { name: worldState.meta.playerName, hp: 100, maxHp: 100, level: 1, inventory: [] },
            roomContext: blueprint,
          },
          [],
          2
        )
      );
    }
    if (npc.questSeed) {
      questTasks.push(
        makeBranchTask(
          'quest',
          'quest',
          {
            questSeed: npc.questSeed,
            worldState: worldStateSnapshot(worldState),
            currentDepth: 0,
            maxDepth: MAX_QUEST_DEPTH,
          },
          [],
          2
        )
      );
    }
  }

  await resolveParallel([...questTasks, ...combatTasks], worldState);

  // Collect quest results + recursive expansion
  for (const qTask of questTasks) {
    const { nodes, hasOpenBranches, seeds } = asQuestNodes(qTask.result);
    if (nodes.length > 0) {
      const questId = `quest_${makeId()}`;
      worldState.quests[questId] = nodes;

      // Recurse up to MAX_QUEST_DEPTH
      if (hasOpenBranches && seeds.length > 0 && qTask.depth < MAX_QUEST_DEPTH) {
        const subQuestTasks = seeds.map((seed) =>
          makeBranchTask(
            'quest',
            'quest',
            {
              questSeed: seed,
              worldState: worldStateSnapshot(worldState),
              currentDepth: qTask.depth + 1,
              maxDepth: MAX_QUEST_DEPTH,
            },
            [],
            qTask.depth + 1
          )
        );
        await resolveParallel(subQuestTasks, worldState);
        for (const subTask of subQuestTasks) {
          const sub = asQuestNodes(subTask.result);
          if (sub.nodes.length > 0) {
            worldState.quests[`quest_${makeId()}`] = sub.nodes;
          }
        }
      }
    }
  }

  // Collect combat results
  for (const cTask of combatTasks) {
    const combat = asCombat(cTask.result, '');
    if (combat) {
      // Store in the NPC's slot — attach to worldState modules
      worldState.typeRegistry.modules[`combat_${combat.npcId}`] = JSON.stringify(combat);
    }
  }

  // Update generation status to "coded"
  room.generationStatus = 'coded';

  // ---- Phase 4: Code generation (non-blocking, best effort) ---
  const codeTargets = [
    { type: 'room' as const, data: room },
    ...npcResults.map((n) => ({ type: 'npc' as const, data: n })),
  ];

  const codeTasks = codeTargets.map((target) =>
    makeBranchTask(
      'code',
      'code-writer',
      {
        blueprint: target.data,
        existingTypes: worldState.typeRegistry,
      },
      [],
      3
    )
  );

  await resolveParallel(codeTasks, worldState);

  // Apply type registry patches
  for (const cTask of codeTasks) {
    if (cTask.result && typeof cTask.result === 'object') {
      const r = cTask.result as { typeRegistryPatch?: { interfaces?: Record<string, string>; classes?: Record<string, string>; modules?: Record<string, string> }; filePath?: string };
      if (r.typeRegistryPatch) {
        const patch = r.typeRegistryPatch;
        if (patch.interfaces) Object.assign(worldState.typeRegistry.interfaces, patch.interfaces);
        if (patch.classes) Object.assign(worldState.typeRegistry.classes, patch.classes);
        if (patch.modules) Object.assign(worldState.typeRegistry.modules, patch.modules);
      }
    }
  }

  // ---- Phase 5: Lore generation -------------------------------
  const loreTargets: Array<{ id: string; type: LoreEntry['targetType'] }> = [
    { id: roomId, type: 'room' },
    ...npcResults.map((n) => ({ id: n.id, type: 'npc' as const })),
  ];

  const loreTasks = loreTargets.map(({ id, type }) =>
    makeBranchTask(
      'lore',
      'lore',
      {
        target: type === 'room' ? room : worldState.npcs[id],
        worldState: worldStateSnapshot(worldState),
        consistencyContext: Object.keys(worldState.consistencyFlags),
      },
      [],
      3
    )
  );

  await resolveParallel(loreTasks, worldState);

  const newLoreEntries: LoreEntry[] = [];
  for (let i = 0; i < loreTasks.length; i++) {
    const loreTask = loreTasks[i];
    const target = loreTargets[i];
    const entry = asLoreEntry(loreTask.result, target.id, target.type);
    if (entry) {
      worldState.loreEntries[entry.id] = entry;
      newLoreEntries.push(entry);
      // Set room's loreEntryId to the first room lore entry found
      if (target.type === 'room') {
        room.loreEntryId = entry.id;
      }
      // Register consistency flags
      for (const flag of entry.consistencyFlags) {
        worldState.consistencyFlags[flag] = true;
      }
    }
  }

  room.generationStatus = 'lored';

  // ---- Phase 6: Lore consistency check (with circuit breaker) --
  let patchIteration = 0;
  let consistencyInput: Record<string, unknown> = {
    worldState: worldStateSnapshot(worldState),
    newEntries: newLoreEntries,
    affectedRoomIds: [roomId],
  };

  while (patchIteration < MAX_LORE_PATCH_ITERATIONS) {
    let consistencyResult: unknown = null;
    try {
      consistencyResult = await callAgent(
        'lore-consistency',
        consistencyInput,
        getMaxTokensForAgent('lore-consistency')
      );
    } catch {
      break;
    }

    const cr = consistencyResult as { consistent?: boolean; patchTargets?: PatchTarget[] };
    if (cr.consistent !== false) break;

    const patchTargets: PatchTarget[] = Array.isArray(cr.patchTargets) ? cr.patchTargets : [];
    if (patchTargets.length === 0) break;

    // Retroactive re-decomposition — spawn lore re-gen for each patch target
    const patchTasks = patchTargets.map((pt) =>
      makeBranchTask(
        'lore',
        'lore',
        {
          target: pt,
          worldState: worldStateSnapshot(worldState),
          consistencyContext: Object.keys(worldState.consistencyFlags),
        },
        [],
        4
      )
    );

    await resolveParallel(patchTasks, worldState);
    const patchedEntries: LoreEntry[] = [];
    for (let i = 0; i < patchTasks.length; i++) {
      const pt = patchTargets[i];
      const entry = asLoreEntry(patchTasks[i].result, pt.targetId, pt.targetType);
      if (entry) {
        worldState.loreEntries[entry.id] = entry;
        patchedEntries.push(entry);
        for (const flag of entry.consistencyFlags) {
          worldState.consistencyFlags[flag] = true;
        }
      }
    }

    consistencyInput = {
      worldState: worldStateSnapshot(worldState),
      newEntries: patchedEntries,
      affectedRoomIds: patchTargets.map((p) => p.targetId),
    };
    patchIteration++;
  }

  // ---- Phase 7: Finalize -------------------------------------
  room.generationStatus = 'complete';
  worldState.openBranches = [];

  logDecomposition(worldState, {
    turnId,
    agentCalled: 'orchestrator',
    inputSummary: `generateRoom(${roomId})`,
    outputSummary: `complete: ${npcResults.length} NPCs, ${newLoreEntries.length} lore entries`,
    branchesSpawned: [],
    branchesClosed: [roomId],
  });

  await saveWorldState(worldState);
  console.log(`[orchestrator] Room ${roomId} generation complete.`);
}

// ============================================================
// Handle player action
// ============================================================

export async function handlePlayerAction(
  action: PlayerAction,
  worldState: WorldState
): Promise<GameResponse> {
  const messages: string[] = [];

  if (action.type === 'move' && action.targetRoomId) {
    const targetId = action.targetRoomId;

    // Generate room if it doesn't yet exist
    if (!worldState.rooms[targetId]) {
      messages.push('The world shimmers as reality fills in around you...');
      await generateRoom(targetId, worldState);
    }

    worldState.meta.currentRoomId = targetId;
    worldState.meta.turnCount++;
  }

  return buildGameResponse(worldState, messages);
}

// ============================================================
// Build GameResponse from current world state
// ============================================================

function buildGameResponse(worldState: WorldState, messages: string[]): GameResponse {
  const roomId = worldState.meta.currentRoomId;
  const room = worldState.rooms[roomId];

  if (!room) {
    return {
      description: 'You are lost in the void.',
      roomId,
      availableExits: [],
      npcs: [],
      items: [],
      messages,
    };
  }

  // Find lore text for the room
  const loreEntry = room.loreEntryId ? worldState.loreEntries[room.loreEntryId] : undefined;
  const description = loreEntry?.text ?? room.title ?? `A ${room.zone} chamber at depth ${room.depth}.`;

  // Build exits
  const availableExits = Object.values(room.exits)
    .filter((e): e is ExitDescriptor => e !== null && e !== undefined)
    .map((e) => ({
      direction: e.direction,
      description: e.description,
      targetRoomId: e.targetRoomId,
    }));

  // Build NPC list
  const npcs = room.npcSlots
    .map((id) => worldState.npcs[id])
    .filter((n): n is NPCDefinition => n !== undefined)
    .map((n) => ({ id: n.id, name: n.name, description: n.description }));

  // Build item list
  const items = room.itemSlots
    .map((id) => worldState.items[id])
    .filter((item) => item !== undefined)
    .map((item) => ({ id: item.id, name: item.name, description: item.description }));

  return {
    description,
    roomId,
    roomTitle: room.title,
    availableExits,
    npcs,
    items,
    messages,
  };
}

// Public alias used by main.ts
export function buildGameResponseFromState(worldState: WorldState): GameResponse {
  return buildGameResponse(worldState, []);
}
