# How Weapons Compute and Apply Damage to Targets

## Overview
DOOM's damage system uses a hitscan model for instant-hit weapons (pistol, shotgun, chaingun) and projectile models for explosive weapons (rocket, plasma, BFG). Damage computation varies by weapon type and incorporates randomization for gameplay balance.

## Hitscan Weapons: Pistol, Shotgun, Chaingun

### Fire Sequence
1. **Weapon action fired** (p_pspr.c:647-662, 669-688, 733-754)
   - A_FirePistol, A_FireShotgun, A_FireCGun trigger weapon animations
   - Ammo decremented before attack

2. **Damage computation**
   - Pistol/Chaingun: P_GunShot (p_pspr.c:626-640)
     - Damage = 5 × (random 0-2 + 1) = 5-15 per shot
     - Called once per fire
   - Shotgun: A_FireShotgun (p_pspr.c:669-688)
     - Calls P_GunShot 7 times for spread pellets
     - Each pellet: 5 × (random 0-2 + 1) = 5-15
     - Total: 35-105 damage distributed across pellets
   - Double Shotgun: A_FireShotgun2 (p_pspr.c:696-726)
     - 20 individual P_LineAttack calls
     - Damage per shot: 5 × (random 0-2 + 1)
     - Spread with angle randomization (±noise)

3. **Raycast and hit detection**: P_LineAttack (p_map.c:1063-1086)
   - Traces ray from shooter position at angle/slope
   - Calls P_PathTraverse which invokes PTR_ShootTraverse (p_map.c:899-1016)
   - PTR_ShootTraverse finds line/thing intersection first

4. **Target damage application**: PTR_ShootTraverse (p_map.c:999-1011)
   - Spawns blood/puff sprite at impact
   - Calls P_DamageMobj(target, shooter, shooter, la_damage) where la_damage is set in P_LineAttack (p_map.c:1075)

## Projectile Weapons: Rocket, Plasma, BFG

### Spawn and Travel
1. **Player projectile spawn**: P_SpawnPlayerMissile (p_mobj.c:935-990)
   - Calls P_AimLineAttack (p_map.c:1023+) to find linetarget via aim slopes
   - If target found, aims at it; otherwise aims straight ahead with fallback angles
   - Spawns missile with velocity toward destination (p_mobj.c:898-927)

2. **Projectile properties** (info.c defines per-type):
   - MT_ROCKET (info.c:1966-1989): spawnhealth=1000, uses A_Explode action
   - MT_PLASMA (info.c:1992-2016): spawnhealth=1000
   - MT_BFG (info.c:2018+): spawnhealth=1000
   - Each type has MF_MISSILE flag and explicit speed

### Impact and Explosion
1. **Rocket/Plasma impact**: Object collision triggers state transition to explosion state
   - Calls A_Explode (p_enemy.c:1598-1601) on impact

2. **Splash damage via P_RadiusAttack** (p_map.c:1206-1233)
   - Called by A_Explode with damage=128 for rockets
   - Iterates map blocks within (damage + MAXRADIUS) distance
   - For each thing: PIT_RadiusAttack (p_map.c:1160-1198)
     - Calculates dist = max(|dx|, |dy|) - thing->radius (Chebyshev distance)
     - If dist >= bombdamage, target out of range (returns true)
     - If P_CheckSight passes (direct line of sight check):
       - **Applies: bombdamage - dist** to target (p_map.c:1194)
     - Boss spider and cyborg immune (p_map.c:1175-1177)
   - Distance falloff: Full damage at epicenter, decreases to zero at radius edge

## BFG9000 Special Attack

### Spray mechanism (p_pspr.c:781-811): A_BFGSpray
1. When BFG projectile impacts, calls A_BFGSpray
2. Loops 40 times at 4.5° angle increments around impact point
3. For each angle: P_AimLineAttack to find targets in view cone
4. **Per-target damage** (p_pspr.c:805-809):
   - damage = sum of 15 random rolls: each (0-7 + 1) = 1-8
   - Total: 15-120 per target hit
   - Called as P_DamageMobj(target, bfg_projectile, player, damage)
5. Spawns MT_EXTRABFG sprite at target location for visual effect

## Damage Application: P_DamageMobj (p_inter.c:775-914)

### Core function signature and parameters
- P_DamageMobj(mobj_t* target, mobj_t* inflictor, mobj_t* source, int damage)
- target: thing receiving damage
- inflictor: object causing damage (weapon/missile/source)
- source: attacker to set as target after damage (usually player/shooter)
- damage: raw damage amount

### Player-specific processing (p_inter.c:799-884)
- Baby difficulty: damage >>= 1 (50% reduction)
- God mode / Invulnerability: return early if damage < 1000 (infinite protection except telefrag)
- Armor absorption (p_inter.c:854-869):
  - Green armor: saves damage/3
  - Blue armor: saves damage/2
  - Stops when armor points exhausted
  - Remaining damage after armor applied to health
- Damage display: damagecount updated for screen flash effect

### Enemy processing (p_inter.c:886-914)
- target->health -= damage
- If health <= 0: P_KillMobj called
- If alive: pain chance roll (p_inter.c:894) may trigger pain state
- Knockback thrust calculation (p_inter.c:817-832):
  - thrust = damage × (FRACUNIT>>3) × 100 / target->mass
  - Applied along angle from inflictor to target
  - Chainsaw exception: no thrust (melee only)
  - Falls forward if damage 40-borderline-lethal and target elevated

## Summary Table

| Weapon | Fire Rate | Damage/Shot | Spread | Special |
|--------|-----------|-------------|--------|---------|
| Pistol | 1 shot | 5-15 | None | Accurate when not refire |
| Shotgun | 1 load/7 pellets | 35-105 total | 7-way spread | Hitscan |
| Chaingun | Rapid fire | 5-15 each | ±noise | Alternates angles |
| Double SG | 1 load/20 shots | Variable | Wide spread | 20 individual traces |
| Rocket | 1/launch | 0-128 splash | N/A | Distance falloff, 128 radius max |
| Plasma | 1/launch | Impact varies | N/A | Instant projectile |
| BFG9000 | 1/charge | 15-120 per target | 40-cone spray | Multi-target, no falloff per target |

## Key Implementation Details

- **Randomization**: All damage uses P_Random() % range to add unpredictability
- **Distance effects**: Only splash weapons (rocket, P_RadiusAttack) apply distance falloff
- **Line of sight**: Splash damage requires P_CheckSight; BFG spray uses P_AimLineAttack
- **Thrust physics**: Applied perpendicular to shooter, scaled by mass (info->mass field)
- **State-driven**: Weapon fire is state-machine callback (action.acp2 in state_t)
