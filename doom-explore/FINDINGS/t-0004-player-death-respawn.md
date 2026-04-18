# Player Death and Respawn in DOOM

## Summary
Player death transitions the player into a corpse state with weapon drop, display of gibbed frames, and respawn triggered by pressing use. Respawn differs between singleplayer (level reload) and netgame (new spawn point selection).

## (a) P_KillMobj Player Death Handler

**Location:** `p_inter.c:668`

When `P_KillMobj` is called with a player as target:

1. **Player state transition** (`p_inter.c:706`): Sets `target->player->playerstate = PST_DEAD`
2. **Weapon drop** (`p_inter.c:707`): Calls `P_DropWeapon(target->player)` to remove active weapon
3. **Corpse flags** (`p_inter.c:675`, `680`, `705`): 
   - Clears `MF_SHOOTABLE|MF_FLOAT|MF_SKULLFLY` flags
   - Adds `MF_CORPSE|MF_DROPOFF` flags
   - Removes `MF_SOLID` flag so the corpse doesn't block movement
   - Reduces height by 1/4 (`p_inter.c:681`)
4. **Gibs threshold** (`p_inter.c:719-725`): If player health drops below negative spawn health, sets extreme death state (`xdeathstate`); otherwise sets normal death state. Animation tics reduced by random 0-3 frames.
5. **Monster/environment kill tracking** (`p_inter.c:692-703`): Increments kill count and frag stats

## (b) Dead Player Think Loop and Respawn Trigger

**Location:** `p_user.c:182-229`

`P_DeathThink` executes each frame while player is in `PST_DEAD` state:

1. **View height fade** (`p_user.c:190-194`): Decreases viewheight toward floor (6 units)
2. **Turning toward attacker** (`p_user.c:200-222`): If an attacker exists, player's view angle rotates toward them; damage flash fades
3. **Respawn trigger** (`p_user.c:227-228`): **Pressing USE button (`BT_USE`) transitions `playerstate` to `PST_REBORN`**
   - This is the critical respawn event—player must actively press use to initiate rebirth

Checked in main think loop at `p_user.c:258-262`: If `playerstate == PST_DEAD`, only `P_DeathThink` runs; all movement/attack logic skipped.

## (c) G_DoReborn Respawn Flow

**Location:** `g_game.c:924-967`

Two distinct paths based on game mode:

**Singleplayer** (`g_game.c:928-931`):
- Sets `gameaction = ga_loadlevel`
- Entire map reloads from scratch
- No `G_PlayerReborn` call in singleplayer path

**Netgame** (`g_game.c:933-966`):
1. Dissociates corpse: `players[playernum].mo->player = NULL` (`g_game.c:938`)
2. Deathmatch mode (`g_game.c:941-945`): Calls `G_DeathMatchSpawnPlayer()` for random spawn selection
3. Cooperative mode (`g_game.c:947-965`):
   - Tries primary spawn point via `G_CheckSpot()` + `P_SpawnPlayer()`
   - Falls back to other players' spawn points if occupied
   - Forcibly spawns at primary point if no free spots available
4. **All netgame paths call `G_PlayerReborn()`** before `P_SpawnPlayer()` (see next section)

## (d) Player State Reset and Spawn Point Selection

**G_PlayerReborn** (`g_game.c:800-833`):
Resets player structure while preserving statistics:
- Preserves frags, kill count, item count, secret count (`g_game.c:809-820`)
- Clears all other data via `memset()` (`g_game.c:815`)
- Sets `playerstate = PST_LIVE` (`g_game.c:823`)
- Resets health to `MAXHEALTH` (`g_game.c:824`)
- Resets weapons: `wp_pistol` as ready/pending (`g_game.c:825`), fist and pistol owned (`g_game.c:826-827`), 50 clip ammo (`g_game.c:828`)
- Sets max ammo values (`g_game.c:830-831`)

**G_CheckSpot** (`g_game.c:844-889`):
Validates spawn point and manages corpse queue:
- First spawn (no existing player mobj): Returns `true` if no other player occupies exact coordinates (`g_game.c:855-863`)
- Respawn: Calls `P_CheckPosition()` to verify no collision at spawn point (`g_game.c:868-869`)
- **Corpse management** (`g_game.c:872-875`): Maintains queue of body corpses; oldest corpse removed if queue full (max `BODYQUESIZE`)
- **Teleport fog effect** (`g_game.c:877-883`): Spawns fog mobj at spawn location with sound (if not initial frame)
- Returns `false` if position occupied; `true` if spawn valid

**P_SpawnPlayer** (`p_mobj.c:642-700`):
Final spawn step that creates player mobj:
- Calls `G_PlayerReborn()` if `playerstate == PST_REBORN` (`p_mobj.c:659-660`)
- Creates mobj at spawn point on floor (`p_mobj.c:662-665`)
- Sets angle, color translation for multiplayer (`p_mobj.c:668-671`)
- Links mobj to player: `mobj->player = p`, `p->mo = mobj` (`p_mobj.c:672-675`)
- Sets `playerstate = PST_LIVE` (`p_mobj.c:676`)
- Resets transient player state: refire, message, damage/bonus counters, color map, view height (`p_mobj.c:677-683`)
- Sets up weapon sprite (`p_mobj.c:686`)
- In deathmatch: gives all keycards (`p_mobj.c:689-691`)
- Reinitializes UI if console player (`p_mobj.c:693-699`)

---

## Key Insights

- **Death is not instant**: Player becomes corpse (non-solid, non-shootable) but retains visibility and animation
- **Respawn is voluntary**: Player must press USE while dead; dead state persists until input received
- **Corpse lifecycle**: Old corpses managed in fixed-size queue; oldest removed when queue full
- **Multiplayer asymmetry**: Singleplayer reloads entire level; netgame respawns at new spawn point without level reset
