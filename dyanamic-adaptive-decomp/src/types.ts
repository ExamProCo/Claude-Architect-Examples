// ============================================================
// Core enums and primitives
// ============================================================

export enum Direction {
  north = 'north',
  south = 'south',
  east = 'east',
  west = 'west',
}

// ============================================================
// Room types
// ============================================================

export interface ExitDescriptor {
  direction: Direction;
  type: 'open' | 'door' | 'locked' | 'hidden' | 'blocked';
  targetRoomId: string;
  description?: string;
}

export type RoomFeature = 'puzzle' | 'trap' | 'shrine' | 'chest' | 'altar' | 'portal' | 'fountain' | 'ruin';

export interface NPCSlot {
  id: string;
  type: 'guard' | 'merchant' | 'enemy' | 'neutral' | 'boss' | 'spirit';
  importance?: 'minor' | 'major' | 'critical';
}

export interface ItemSlot {
  id: string;
  type: 'weapon' | 'armor' | 'potion' | 'key' | 'artifact' | 'lore' | 'currency';
  rarity?: 'common' | 'uncommon' | 'rare' | 'legendary';
}

export interface Room {
  id: string;
  zone: string;
  depth: number;
  title?: string;
  exits: Partial<Record<Direction, ExitDescriptor | null>>;
  npcSlots: string[];
  itemSlots: string[];
  features: RoomFeature[];
  codeFile: string;
  loreEntryId: string;
  generationStatus: 'blueprint' | 'coded' | 'lored' | 'complete';
}

export interface RoomBlueprint {
  structuralDescription: string;
  title?: string;
  exits: ExitDescriptor[];
  npcSlots: NPCSlot[];
  itemSlots: ItemSlot[];
  features: RoomFeature[];
  atmosphereHints: string[];
  narrativeWeight: 'low' | 'medium' | 'high' | 'climactic';
}

// ============================================================
// NPC types
// ============================================================

export interface NPCDefinition {
  id: string;
  name: string;
  type: NPCSlot['type'];
  description: string;
  dialogueTree: Record<string, string>;
  behaviorFlags: {
    isQuestGiver: boolean;
    isCombatant: boolean;
    isInformant: boolean;
  };
  stats: {
    hp: number;
    attack: number;
    defense: number;
    level: number;
  };
  questSeed?: QuestSeed;
}

// ============================================================
// Quest types
// ============================================================

export interface QuestSeed {
  id: string;
  title: string;
  hook: string;
  suggestedDepth: number;
  themeHints: string[];
}

export interface QuestNode {
  id: string;
  title: string;
  description: string;
  objectives: string[];
  rewards: {
    xp?: number;
    items?: string[];
    flags?: string[];
  };
  isTerminal: boolean;
  parentId?: string;
}

export interface QuestNodeSeed {
  parentNodeId: string;
  branchHint: string;
  suggestedType: 'fetch' | 'kill' | 'explore' | 'talk' | 'deliver';
}

// ============================================================
// Lore types
// ============================================================

export interface LoreEntry {
  id: string;
  targetId: string;
  targetType: 'room' | 'npc' | 'item' | 'quest';
  text: string;
  consistencyFlags: string[];
}

// ============================================================
// Item types
// ============================================================

export interface ItemDefinition {
  id: string;
  name: string;
  type: ItemSlot['type'];
  description: string;
  stats?: Record<string, number>;
  questRelevant?: boolean;
}

// ============================================================
// Combat types
// ============================================================

export interface CombatModule {
  npcId: string;
  attackPatterns: Array<{
    name: string;
    damage: number;
    description: string;
    triggerCondition?: string;
  }>;
  defeatConditions: string[];
  lootTable: Array<{
    itemId: string;
    dropChance: number;
  }>;
  phases: number;
  hasPhases: boolean;
  phaseSeeds?: CombatPhaseSeed[];
}

export interface CombatPhaseSeed {
  phaseNumber: number;
  triggerCondition: string;
  behaviorHints: string[];
}

// ============================================================
// Puzzle types
// ============================================================

export interface PuzzleDefinition {
  id: string;
  description: string;
  winCondition: string;
  hints: string[];
  resetBehavior: 'permanent' | 'resettable' | 'timed';
  subPuzzles?: PuzzleSeed[];
}

export interface PuzzleSeed {
  parentPuzzleId: string;
  puzzleType: string;
  complexityHint: 'simple' | 'moderate' | 'complex';
}

// ============================================================
// Type registry and patch targets
// ============================================================

export interface TypeRegistry {
  interfaces: Record<string, string>;
  classes: Record<string, string>;
  modules: Record<string, string>;
}

export interface PatchTarget {
  targetId: string;
  targetType: 'room' | 'npc' | 'item' | 'quest';
  reason: string;
}

// ============================================================
// Branch task (DAD engine)
// ============================================================

export interface BranchTask {
  id: string;
  type: 'room' | 'npc' | 'quest' | 'lore' | 'code' | 'puzzle' | 'combat';
  agentName: string;
  input: Record<string, unknown>;
  dependsOn: string[];
  status: 'pending' | 'running' | 'complete' | 'blocked';
  depth: number;
  result?: unknown;
}

// ============================================================
// Decomposition log
// ============================================================

export interface DecompositionEntry {
  turnId: string;
  agentCalled: string;
  inputSummary: string;
  outputSummary: string;
  branchesSpawned: string[];
  branchesClosed: string[];
  timestamp: string;
}

// ============================================================
// World state
// ============================================================

export interface WorldState {
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
  consistencyFlags: Record<string, boolean>;
  typeRegistry: TypeRegistry;
  decompositionLog: DecompositionEntry[];
  openBranches: BranchTask[];
}

// ============================================================
// Player types
// ============================================================

export interface PlayerAction {
  type: 'move' | 'examine' | 'interact' | 'attack';
  targetRoomId?: string;
  targetId?: string;
  direction?: Direction;
}

export interface GameResponse {
  description: string;
  roomId: string;
  roomTitle?: string;
  availableExits: Array<{
    direction: Direction;
    description?: string;
    targetRoomId: string;
  }>;
  npcs: Array<{
    id: string;
    name: string;
    description: string;
  }>;
  items: Array<{
    id: string;
    name: string;
    description: string;
  }>;
  messages: string[];
}

export interface PlayerStats {
  name: string;
  hp: number;
  maxHp: number;
  level: number;
  inventory: string[];
}
