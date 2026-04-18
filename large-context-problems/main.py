"""
Large Context Problem Demo: Text Adventure Game

Demonstrates two techniques:
1. CASE FACTS: Extract key precision info, store externally, inject as facts each turn
2. TOOL FILTERING: Tool returns massive JSON world state, we filter to only relevant data
"""
import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from anthropic import Anthropic
from pathlib import Path


load_dotenv(Path(__file__).parent.parent / ".env")

# ─── The "massive" world state that a tool would return ──────────────────────
# In real apps this could be gigabytes of logs, a full DB dump, etc.
WORLD_STATE = {
    "metadata": {"version": "1.0", "seed": 42, "total_rooms": 6, "npcs": 12, "quests": 30},
    "rooms": {
        "entrance": {
            "name": "Castle Entrance",
            "description": "A grand hall with stone floors and flickering torches.",
            "exits": {"north": "throne_room", "east": "armory"},
            "items": ["rusty_key", "old_map"],
            "enemies": [],
            "secret": "There is a loose stone behind the tapestry hiding gold coins."
        },
        "throne_room": {
            "name": "Throne Room",
            "description": "A magnificent room with a jeweled throne.",
            "exits": {"south": "entrance", "west": "dungeon"},
            "items": ["royal_crown"],
            "enemies": ["skeleton_guard"],
            "secret": "The throne has a hidden lever underneath."
        },
        "armory": {
            "name": "Armory",
            "description": "Walls lined with ancient weapons and armor.",
            "exits": {"west": "entrance", "north": "library"},
            "items": ["iron_sword", "shield", "crossbow", "arrows", "chain_mail"],
            "enemies": [],
            "secret": None
        },
        "dungeon": {
            "name": "Dark Dungeon",
            "description": "A damp, dark pit that smells of decay.",
            "exits": {"east": "throne_room"},
            "items": ["rusty_dagger", "torch"],
            "enemies": ["dungeon_rat", "dungeon_rat", "dark_wraith"],
            "secret": "A prisoner in cell 7 knows where the treasure is buried."
        },
        "library": {
            "name": "Ancient Library",
            "description": "Dusty tomes line every wall from floor to ceiling.",
            "exits": {"south": "armory"},
            "items": ["spell_book", "scroll_of_fireball"],
            "enemies": [],
            "secret": "The red book on the third shelf is a disguised door."
        },
        "treasury": {
            "name": "Hidden Treasury",
            "description": "Piles of gold and ancient artifacts.",
            "exits": {},
            "items": ["dragon_treasure", "ancient_relic", "magic_amulet"],
            "enemies": ["treasure_guardian"],
            "secret": None
        }
    },
    # Lots of irrelevant bulk data a real API might return
    "npc_schedules": {f"npc_{i}": {"routine": "wander", "mood": "neutral"} for i in range(50)},
    "quest_log": {f"quest_{i}": {"status": "inactive", "reward": i * 10} for i in range(30)},
    "weather_history": [{"day": i, "temp": 20 + i % 5, "rain": i % 3 == 0} for i in range(365)],
    "lore_entries": {f"lore_{i}": f"Ancient text entry {i}..." for i in range(100)},
}

CASE_FACTS_FILE = Path(__file__).parent / "case_facts.json"


# ─── Tool: returns the FULL world state (simulating a bloated API response) ──
def get_world_state_tool() -> dict:
    """Simulates a tool returning massive JSON. We'll filter it down."""
    return WORLD_STATE  # In reality: requests.get("/api/full-world").json()


# ─── TECHNIQUE 1: Tool Output Filtering ──────────────────────────────────────
def get_current_room(room_id: str) -> dict:
    """
    Filter the massive world state down to ONLY what's needed for this turn.
    Instead of injecting thousands of tokens, we inject ~50 tokens of facts.
    """
    world = get_world_state_tool()
    room = world["rooms"].get(room_id, {})
    # Return only the relevant slice — not the full world
    return {
        "name": room.get("name"),
        "description": room.get("description"),
        "exits": room.get("exits", {}),
        "items": room.get("items", []),
        "enemies": room.get("enemies", []),
    }


# ─── TECHNIQUE 2: Case Facts ─────────────────────────────────────────────────
def load_case_facts() -> dict:
    """Load persisted player facts from disk (simulating external storage)."""
    if CASE_FACTS_FILE.exists():
        return json.loads(CASE_FACTS_FILE.read_text())
    return {
        "current_room": "entrance",
        "inventory": [],
        "visited_rooms": [],
        "health": 100,
        "discoveries": [],
        "turns": 0,
    }


def save_case_facts(facts: dict):
    """Persist case facts externally so they survive across sessions."""
    CASE_FACTS_FILE.write_text(json.dumps(facts, indent=2))


def extract_case_facts_from_response(response_text: str, current_facts: dict) -> dict:
    """
    Extract key precision info from the AI response and update case facts.
    This is the 'distillation' step — we keep only what matters.
    """
    text = response_text.lower()
    facts = dict(current_facts)
    facts["turns"] += 1

    # Track room visits
    room = facts["current_room"]
    if room not in facts["visited_rooms"]:
        facts["visited_rooms"].append(room)

    # Extract item pickups (simple pattern matching — real apps use structured output)
    world_items = WORLD_STATE["rooms"].get(room, {}).get("items", [])
    for item in world_items:
        if f"pick up {item.replace('_', ' ')}" in text or f"take {item.replace('_', ' ')}" in text:
            if item not in facts["inventory"]:
                facts["inventory"].append(item)

    # Extract movement
    exits = WORLD_STATE["rooms"].get(room, {}).get("exits", {})
    for direction, dest_room in exits.items():
        if f"go {direction}" in text or f"move {direction}" in text or f"head {direction}" in text:
            facts["current_room"] = dest_room
            break

    # Extract discoveries
    if "secret" in text or "discover" in text or "hidden" in text:
        discovery = f"Found something secret in {room}"
        if discovery not in facts["discoveries"]:
            facts["discoveries"].append(discovery)

    return facts


# ─── Build the system prompt with injected case facts ────────────────────────
def build_system_prompt(facts: dict) -> str:
    room_data = get_current_room(facts["current_room"])

    return f"""You are a narrator for a text adventure game. Be concise and vivid.

## CASE FACTS (precision state — do not ignore these)
- Current Room: {facts['current_room']} — {room_data['name']}
- Health: {facts['health']}/100
- Inventory: {facts['inventory'] or 'empty'}
- Visited: {facts['visited_rooms'] or 'none yet'}
- Key Discoveries: {facts['discoveries'] or 'none yet'}
- Turn: {facts['turns']}

## CURRENT ROOM (filtered from world state)
- Description: {room_data['description']}
- Exits: {room_data['exits']}
- Items here: {room_data['items']}
- Enemies: {room_data['enemies']}

Respond to the player's action. End with a prompt asking what they do next.
If they pick up items, move rooms, or make discoveries — narrate it clearly so state can be tracked."""


# ─── Main game loop ───────────────────────────────────────────────────────────
async def main():
    client = Anthropic(
        # This is the default and can be omitted
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    facts = load_case_facts()

    print("=" * 60)
    print("TEXT ADVENTURE: Large Context Demo")
    print("=" * 60)
    print("\nTECHNIQUE 1 — Tool Filtering:")
    print(f"  World state size: {len(json.dumps(WORLD_STATE)):,} chars")
    print(f"  Filtered room size: {len(json.dumps(get_current_room(facts['current_room']))):,} chars")
    print("\nTECHNIQUE 2 — Case Facts:")
    print(f"  Persisted to: {CASE_FACTS_FILE}")
    print("=" * 60)
    print("\nType 'quit' to exit. Try: 'look around', 'go north', 'pick up rusty key'\n")

    while True:
        player_input = input("You: ").strip()
        if player_input.lower() in ("quit", "exit", "q"):
            print("Game saved. Goodbye!")
            break
        if not player_input:
            continue

        system = build_system_prompt(facts)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": player_input}],
        )

        reply = response.content[0].text
        print(f"\nNarrator: {reply}\n")

        # Extract precision facts from response and persist
        facts = extract_case_facts_from_response(reply, facts)
        save_case_facts(facts)

        print(f"[Facts: room={facts['current_room']}, hp={facts['health']}, inv={facts['inventory']}]")
        print()


if __name__ == "__main__":
    asyncio.run(main())
