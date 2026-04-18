# t-0001: How does a player take damage?

## Question
What is the sequence of events and data transformations when a player character receives damage in DOOM?

## Entry points
- `p_map.c:279` — Projectile collision damage during trace/impact
- `p_map.c:1011` — Hitscan weapon damage during raycast
- `p_map.c:1194` — Blast radius damage propagation
- `p_spec.c:1026,1033,1044,1059` — Environmental damage (lava, slime, crushing)
- `p_enemy.c:925,946,961,990,1114,1324` — Monster melee/projectile attacks

## Call chain
1. Various game systems call `P_DamageMobj` (p_inter.c:775)
2. Target player check: player pointer extracted from target mobj (p_inter.c:798)
3. Baby difficulty reduction: damage halved for player in trainer mode (p_inter.c:799-800)
4. Armor absorption: based on armor type (1=1/3, 2=1/2), armor points deducted, remaining damage reduced (p_inter.c:854-869)
5. Health decrement: player health reduced by damage after armor (p_inter.c:870)
6. Damage UI tracking: damagecount incremented for HUD flash effect (p_inter.c:875-878)
7. Invulnerability/God mode check: extreme damage (≥1000) bypasses both; normal damage ignored if either active (p_inter.c:847-852)
8. Pain state transition: target set to pain state based on painchance random roll (p_inter.c:894-900)
9. Death check: if health ≤ 0, `P_KillMobj` called (p_inter.c:888-891)

## Key files
- `p_inter.c:775-917` — P_DamageMobj implementation; full damage logic including armor, health, and pain states
- `p_inter.c:668-758` — P_KillMobj; death state transition, corpse setup, item drops
- `d_player.h:83-150` — player_t structure; armorpoints (int), armortype (0-2), health (int), powers[] (invulnerability tracking), damagecount (HUD flash counter)
- `p_local.h:269` — P_DamageMobj declaration

## Summary
Player damage in DOOM flows through P_DamageMobj, a central function called by projectiles, hitscan weapons, explosions, and environmental hazards. The function first applies difficulty modifiers (half damage on baby mode), then processes armor absorption based on armor type: type 1 absorbs 1/3 of damage, type 2 absorbs 1/2. After armor deduction, remaining damage is subtracted from player health. Invulnerability powerups and god mode (except for massive 1000+ damage) provide complete immunity. The damage is tracked in damagecount for HUD flash effects. If health reaches zero, P_KillMobj transitions the player to death state. The function also triggers pain animations probabilistically and updates target tracking for monsters.

## Open follow-ups
- What is the exact painchance probability mechanism?
- How do specific weapon types calculate base damage values?
- What happens during the invulnerability powerup grace period (pw_invulnerability duration)?
- How does monster splash damage differ from direct projectile damage?
