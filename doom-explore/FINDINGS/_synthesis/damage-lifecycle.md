# Damage Lifecycle Synthesis: Damage, Armor, Weapons, and Death

## Answer

DOOM's damage pipeline forms a complete lifecycle: weapons or environmental hazards inflict damage, which flows through a central damage handler (P_DamageMobj) that applies armor absorption before reducing player health. Once health reaches zero, death is triggered via P_KillMobj, transitioning the player to a corpse state with animation and voluntary respawn through the USE key.

## Consolidated Call Chain

```
Weapon/Environmental System
├─ Hitscan weapons (pistol, shotgun, chaingun)
│  ├─ P_GunShot computes randomized damage (5-15 per shot)
│  ├─ P_LineAttack traces ray and invokes PTR_ShootTraverse
│  └─ PTR_ShootTraverse → P_DamageMobj(target, shooter, shooter, damage)
│
├─ Projectile weapons (rocket, plasma, BFG)
│  ├─ P_SpawnPlayerMissile creates missile with velocity
│  ├─ Impact triggers A_Explode
│  ├─ A_Explode → P_RadiusAttack for splash damage (distance falloff: damage - dist)
│  └─ BFG spray: A_BFGSpray loops 40 times, each angle: P_DamageMobj(target, bfg, player, 15-120)
│
└─ Environmental (lava, slime, crushing, monster melee/ranged)
   └─ P_DamageMobj(player, source, source, environmental_damage)

P_DamageMobj (p_inter.c:775-917) [CENTRAL DAMAGE HANDLER]
├─ Difficulty modifier (baby mode): damage >>= 1 (halve)
├─ Invulnerability/God mode check: return if damage < 1000
├─ Armor Absorption (ARMOR INTEGRATION)
│  ├─ If armortype == 1 (green): saved = damage / 3
│  ├─ If armortype == 2 (blue): saved = damage / 2
│  ├─ Cap saved by remaining armorpoints
│  ├─ Deduct saved from both armorpoints and incoming damage
│  ├─ Reset armortype to 0 when armorpoints depleted
│  └─ Apply remaining damage to health
├─ Damage UI tracking: damagecount incremented for HUD flash
├─ Pain state: target set to pain state based on painchance roll
└─ Death check: if health ≤ 0 → P_KillMobj

P_KillMobj (p_inter.c:668-758) [DEATH STATE TRANSITION]
├─ Set playerstate = PST_DEAD
├─ Drop weapon via P_DropWeapon
├─ Modify corpse flags: remove MF_SOLID, add MF_CORPSE, reduce height 1/4
├─ Set death/xdeathstate based on health threshold (gibbing)
└─ Player now waits for respawn input (dead loop at p_user.c:182-229)

P_DeathThink (p_user.c:182-229) [DEAD WAIT LOOP]
├─ Fade view height toward floor
├─ Rotate view toward attacker
└─ On BT_USE (USE key) → playerstate = PST_REBORN

G_DoReborn (g_game.c:924-967) [RESPAWN DISPATCH]
├─ Singleplayer: gameaction = ga_loadlevel (reload entire map)
└─ Netgame: G_PlayerReborn → G_CheckSpot → P_SpawnPlayer (respawn at new point)

P_SpawnPlayer (p_mobj.c:642-700) [RESPAWN COMPLETION]
├─ Reset player structure (health=100, weapons reset, ammo=50 clip)
├─ Create new mobj at spawn point
├─ Link player ↔ mobj
├─ Set playerstate = PST_LIVE
└─ Reinitialize weapon sprite and UI
```

## Armor Integration in Damage Flow

Armor sits directly inside P_DamageMobj's player branch (p_inter.c:854-869), applying **before** health reduction:

1. **P_GiveArmor** (pickup) sets armortype (1 or 2) and armorpoints:
   - Type 1 (green): 100-point capacity, saves ⌊damage/3⌋
   - Type 2 (blue): 200-point capacity, saves ⌊damage/2⌋
   - SPR_BON2 (armor bonus): increments by 1, caps at 200, defaults to type 1

2. **Damage absorption** (in P_DamageMobj):
   - Compute saved = damage / armortype_multiplier (integer division)
   - If saved > armorpoints, cap at armorpoints and zero armortype
   - Subtract saved from armorpoints and incoming damage
   - Pass remaining damage through to health

3. **Result**: Armor extends survival by absorbing incoming damage proportionally before health loss occurs.

## Key Files Deduped

| File | Location | Purpose |
|------|----------|---------|
| p_inter.c | 775-917 | P_DamageMobj: central damage handler, armor absorption, pain states |
| p_inter.c | 668-758 | P_KillMobj: death state transition, corpse setup |
| p_inter.c | 252-266 | P_GiveArmor: armor pickup logic |
| p_inter.c | 339-398 | P_TouchSpecialThing: armor pickup dispatch |
| p_user.c | 182-229 | P_DeathThink: dead wait loop, respawn trigger |
| p_mobj.c | 642-700 | P_SpawnPlayer: respawn completion, player creation |
| g_game.c | 924-967 | G_DoReborn: respawn dispatch (singleplayer vs netgame) |
| g_game.c | 800-833 | G_PlayerReborn: player state reset |
| p_map.c | 1063-1086 | P_LineAttack: hitscan raycast and hit detection |
| p_map.c | 899-1016 | PTR_ShootTraverse: line/thing intersection, damage application |
| p_map.c | 1206-1233 | P_RadiusAttack: splash damage with distance falloff |
| p_pspr.c | 626-640 | P_GunShot: hitscan damage computation (5-15 randomized) |
| p_pspr.c | 781-811 | A_BFGSpray: BFG multi-target spray (15-120 per target) |
| p_enemy.c | 1598-1601 | A_Explode: projectile explosion trigger |
| d_player.h | 83-150 | player_t: armorpoints, armortype, health, powers[], damagecount |

## Contradictions

**None detected.** All four scratchpads present consistent mechanics:
- P_DamageMobj applies armor before health (t-0001 § Call chain step 4, t-0002 § Call Chain step 2) — consistent.
- Armor types and capacities (t-0002 § Summary: green=100, blue=200) are not contradicted in other documents.
- Weapon damage computations (t-0003) and their passage to P_DamageMobj are consistent with the damage entry points (t-0001).
- Death logic (t-0004) consistently describes PST_DEAD → PST_REBORN → PST_LIVE transition triggered by USE key.

## Gaps

1. **Painchance probability**: t-0001 notes "What is the exact painchance probability mechanism?" — all scratchpads reference the roll but no RNG formula is provided.
2. **Invulnerability duration**: t-0001 asks about `pw_invulnerability` duration — t-0002 notes the check exists (p_inter.c:847-851) but duration specifics absent.
3. **Boss/Spider immunity**: t-0003 mentions boss spider and cyborg are immune to splash (p_map.c:1175-1177) — no detail on the immunity types or full list.
4. **Armor Bonus edge case**: t-0002 asks if SPR_BON2 can exceed armortype classification — mechanics allow type 1 to reach 200 points via bonuses, but semantic impact unstudied.
5. **Megasphere interaction**: t-0002 notes megasphere (p_inter.c:409-417) may create edge cases — not explored.
6. **Corpse queue details**: t-0004 mentions BODYQUESIZE queue management — maximum queue size and lifecycle not quantified.

## Sources

- (FINDINGS/t-0001-player-damage.md#call-chain) — P_DamageMobj entry point, difficulty, armor, health, pain, death.
- (FINDINGS/t-0001-player-damage.md#key-files) — p_inter.c:775-917, p_inter.c:668-758, d_player.h:83-150.
- (FINDINGS/t-0002-armor-mechanics.md#call-chain) — Armor acquisition (P_TouchSpecialThing, P_GiveArmor) and utilization in P_DamageMobj.
- (FINDINGS/t-0002-armor-mechanics.md#key-files) — p_inter.c:252-266, p_inter.c:339-398, d_player.h:103-105.
- (FINDINGS/t-0003-weapon-damage.md#hitscan-weapons) — P_GunShot, P_LineAttack, PTR_ShootTraverse damage application.
- (FINDINGS/t-0003-weapon-damage.md#projectile-weapons) — P_SpawnPlayerMissile, A_Explode, P_RadiusAttack splash damage.
- (FINDINGS/t-0003-weapon-damage.md#bfg9000-special-attack) — A_BFGSpray 40-loop targeting and per-target damage.
- (FINDINGS/t-0003-weapon-damage.md#key-implementation-details) — Distance falloff, line of sight, thrust physics.
- (FINDINGS/t-0004-player-death-respawn.md#p_killmobj-player-death-handler) — Death state transition, corpse flags, gibs threshold.
- (FINDINGS/t-0004-player-death-respawn.md#dead-player-think-loop-and-respawn-trigger) — P_DeathThink, respawn trigger on USE.
- (FINDINGS/t-0004-player-death-respawn.md#g_doreborn-respawn-flow) — Singleplayer reload vs netgame respawn.
- (FINDINGS/t-0004-player-death-respawn.md#player-state-reset-and-spawn-point-selection) — G_PlayerReborn, G_CheckSpot, P_SpawnPlayer final steps.
