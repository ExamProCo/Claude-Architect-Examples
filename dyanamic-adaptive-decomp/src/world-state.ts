import fs from 'fs/promises';
import path from 'path';
import { WorldState, Room, Direction, ExitDescriptor } from './types';

const WORLD_DIR = path.join(__dirname, '..', 'world');
const WORLD_STATE_FILE = path.join(WORLD_DIR, 'world-state.json');

export async function loadWorldState(sessionId: string): Promise<WorldState> {
  try {
    const raw = await fs.readFile(WORLD_STATE_FILE, 'utf-8');
    const parsed: unknown = JSON.parse(raw);
    // If file is empty object or missing meta, create initial state
    if (
      parsed === null ||
      typeof parsed !== 'object' ||
      !('meta' in (parsed as object))
    ) {
      const initial = createInitialWorldState(sessionId, 'Adventurer');
      await saveWorldState(initial);
      return initial;
    }
    return parsed as WorldState;
  } catch {
    // File doesn't exist or is invalid — create fresh state
    await fs.mkdir(WORLD_DIR, { recursive: true });
    const initial = createInitialWorldState(sessionId, 'Adventurer');
    await saveWorldState(initial);
    return initial;
  }
}

export async function saveWorldState(state: WorldState): Promise<void> {
  await fs.mkdir(WORLD_DIR, { recursive: true });
  await fs.writeFile(WORLD_STATE_FILE, JSON.stringify(state, null, 2), 'utf-8');
}

export function createInitialWorldState(sessionId: string, playerName: string): WorldState {
  const now = new Date().toISOString();

  // Build a fully-realized entrance room so the player has somewhere to start immediately
  const entranceRoom: Room = {
    id: 'entrance',
    zone: 'dungeon-entrance',
    depth: 0,
    title: 'The Dungeon Entrance',
    exits: {
      [Direction.north]: {
        direction: Direction.north,
        type: 'open',
        targetRoomId: 'room_dungeon-entrance_1_north',
        description: 'A dark corridor leads deeper into the dungeon.',
      } as ExitDescriptor,
      [Direction.south]: null,
      [Direction.east]: {
        direction: Direction.east,
        type: 'door',
        targetRoomId: 'room_dungeon-entrance_1_east',
        description: 'A heavy wooden door stands slightly ajar.',
      } as ExitDescriptor,
      [Direction.west]: null,
    },
    npcSlots: [],
    itemSlots: [],
    features: [],
    codeFile: 'world/rooms/entrance.ts',
    loreEntryId: 'lore_entrance',
    generationStatus: 'complete',
  };

  const entranceLore = {
    id: 'lore_entrance',
    targetId: 'entrance',
    targetType: 'room' as const,
    text:
      'You stand at the threshold of an ancient dungeon. Torchlight flickers against moss-covered stone walls, casting dancing shadows across the floor. The air smells of damp earth and forgotten ages. Two paths beckon — a dark corridor stretching north, and a heavy door to the east.',
    consistencyFlags: ['dungeon-entrance-exists', 'torchlit-entrance'],
  };

  return {
    meta: {
      sessionId,
      playerName,
      currentRoomId: 'entrance',
      turnCount: 0,
      generatedAt: now,
    },
    rooms: {
      entrance: entranceRoom,
    },
    npcs: {},
    items: {},
    quests: {},
    loreEntries: {
      lore_entrance: entranceLore,
    },
    consistencyFlags: {
      'dungeon-entrance-exists': true,
      'torchlit-entrance': true,
    },
    typeRegistry: {
      interfaces: {},
      classes: {},
      modules: {},
    },
    decompositionLog: [],
    openBranches: [],
  };
}
