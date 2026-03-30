import * as readline from 'readline';
import { loadWorldState, saveWorldState, createInitialWorldState } from './world-state';
import { handlePlayerAction, buildGameResponseFromState } from './orchestrator';
import { Direction, PlayerAction, GameResponse, WorldState } from './types';

// ============================================================
// Helpers
// ============================================================

function banner(): void {
  console.log('');
  console.log('=== AGENT DUNGEON ===');
  console.log('A world that builds itself as you explore.');
  console.log('');
}

function prompt(rl: readline.Interface, question: string): Promise<string> {
  return new Promise((resolve) => rl.question(question, resolve));
}

function displayRoom(response: GameResponse): void {
  console.log('');
  if (response.roomTitle) {
    console.log(`--- ${response.roomTitle} ---`);
  }
  console.log(response.description);
  console.log('');

  if (response.availableExits.length > 0) {
    const exitList = response.availableExits
      .map((e) => {
        const dir = e.direction.toUpperCase();
        const desc = e.description ? ` (${e.description})` : '';
        return `  [${dir}]${desc}`;
      })
      .join('\n');
    console.log('Exits:');
    console.log(exitList);
  } else {
    console.log('No obvious exits.');
  }

  if (response.npcs.length > 0) {
    console.log('');
    console.log('Present:');
    for (const npc of response.npcs) {
      console.log(`  ${npc.name} — ${npc.description}`);
    }
  }

  if (response.items.length > 0) {
    console.log('');
    console.log('Items:');
    for (const item of response.items) {
      console.log(`  ${item.name} — ${item.description}`);
    }
  }

  if (response.messages.length > 0) {
    console.log('');
    for (const msg of response.messages) {
      console.log(`  > ${msg}`);
    }
  }

  console.log('');
}

function parseDirection(input: string): Direction | null {
  const normalized = input.trim().toLowerCase();
  const map: Record<string, Direction> = {
    north: Direction.north,
    n: Direction.north,
    south: Direction.south,
    s: Direction.south,
    east: Direction.east,
    e: Direction.east,
    west: Direction.west,
    w: Direction.west,
  };
  return map[normalized] ?? null;
}

// ============================================================
// Main game loop
// ============================================================

async function main(): Promise<void> {
  banner();

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  // ---- Session setup ------------------------------------------
  const sessionId = `session_${Date.now()}`;
  let worldState: WorldState = await loadWorldState(sessionId);

  // If this is a fresh state, ask for the player's name
  if (worldState.meta.playerName === 'Adventurer' && worldState.meta.turnCount === 0) {
    const nameInput = (await prompt(rl, 'Enter your name: ')).trim();
    if (nameInput) {
      worldState = createInitialWorldState(sessionId, nameInput);
      await saveWorldState(worldState);
    }
  }

  console.log(`\nWelcome, ${worldState.meta.playerName}!`);
  console.log('Commands: north/south/east/west (n/s/e/w), look, examine <thing>, quit\n');

  // Show the starting room
  displayRoom(buildGameResponseFromState(worldState));

  // ---- Input loop ---------------------------------------------
  while (true) {
    const rawInput = (await prompt(rl, '> ')).trim();

    if (!rawInput) continue;

    const lower = rawInput.toLowerCase();

    // Quit
    if (lower === 'quit' || lower === 'exit' || lower === 'q') {
      console.log('\nFarewell, adventurer. Your journey is saved.\n');
      await saveWorldState(worldState);
      rl.close();
      break;
    }

    // Look / re-describe current room
    if (lower === 'look' || lower === 'l') {
      displayRoom(buildGameResponseFromState(worldState));
      continue;
    }

    // Movement
    const dir = parseDirection(lower);
    if (dir !== null) {
      const currentRoom = worldState.rooms[worldState.meta.currentRoomId];
      if (!currentRoom) {
        console.log('Something is very wrong — you have no current room.');
        continue;
      }

      const exit = currentRoom.exits[dir];
      if (!exit) {
        console.log(`You cannot go ${dir} from here.`);
        continue;
      }

      console.log(`\nYou head ${dir}...`);
      const action: PlayerAction = {
        type: 'move',
        direction: dir,
        targetRoomId: exit.targetRoomId,
      };

      try {
        const response = await handlePlayerAction(action, worldState);
        displayRoom(response);
      } catch (err) {
        console.error('[error] Failed to move:', err);
        console.log('Something went wrong. Try again.');
      }
      continue;
    }

    // Examine <target>
    if (lower.startsWith('examine ') || lower.startsWith('ex ') || lower.startsWith('x ')) {
      const target = rawInput.slice(rawInput.indexOf(' ') + 1).trim();

      // Find the NPC or item in the current room
      const currentRoom = worldState.rooms[worldState.meta.currentRoomId];
      if (currentRoom) {
        const npcId = currentRoom.npcSlots.find((id) => {
          const npc = worldState.npcs[id];
          return npc && npc.name.toLowerCase().includes(target.toLowerCase());
        });
        if (npcId) {
          const npc = worldState.npcs[npcId];
          if (npc) {
            console.log(`\n${npc.name}: ${npc.description}`);
            const loreId = `lore_${npcId}`;
            const lore = worldState.loreEntries[loreId];
            if (lore) console.log(`\n  "${lore.text}"`);
            console.log('');
            continue;
          }
        }
      }

      console.log(`You see nothing notable called "${target}".`);
      continue;
    }

    // Unknown command
    console.log(`Unknown command: "${rawInput}". Try: north, south, east, west, look, quit`);
  }
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
