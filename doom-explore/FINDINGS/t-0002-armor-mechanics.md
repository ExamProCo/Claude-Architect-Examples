# Task t-0002: Armor Pickup and Armor Class Damage Absorption

## Question
How does armor pickup and armor class affect damage absorption?

## Entry Points
1. **Armor Pickup**: `P_TouchSpecialThing()` in p_inter.c:339
   - Dispatches on sprite type (SPR_ARM1, SPR_ARM2, SPR_BON2)
   - Calls `P_GiveArmor()` or directly modifies armor fields

2. **Armor Damage Reduction**: Player damage handler in p_inter.c:854-869
   - Located within `P_DamageMobj()` player branch
   - Applies armor class multiplier before subtracting health

## Call Chain

### Armor Acquisition
```
P_TouchSpecialThing (p_inter.c:339)
  └─ Sprite Type Switch (p_inter.c:367)
     ├─ SPR_ARM1 (Green Armor): P_GiveArmor(player, 1) at p_inter.c:371
     ├─ SPR_ARM2 (Blue Armor): P_GiveArmor(player, 2) at p_inter.c:377
     └─ SPR_BON2 (Armor Bonus): Direct armorpoints increment at p_inter.c:392
```

### Armor Utilization (Damage Reduction)
```
P_DamageMobj() - Player branch (p_inter.c:854-869)
  ├─ Check if armortype != 0
  ├─ Apply class multiplier:
  │  ├─ armortype == 1: saved = damage/3 (33% absorption) at p_inter.c:857
  │  └─ armortype == 2: saved = damage/2 (50% absorption) at p_inter.c:859
  ├─ Cap saved at remaining armorpoints (p_inter.c:861-866)
  ├─ Subtract from armorpoints and damage (p_inter.c:867-868)
  └─ Apply remaining damage to health
```

## Key Files and Line References

### Player Structure (d_player.h)
- `armorpoints` (int): Remaining armor absorption capacity, capped at 200 (d_player.h:103)
- `armortype` (int): Armor classification—0 (none), 1 (green/25%), 2 (blue/50%) (d_player.h:105)
- Comment at d_player.h:104 states "Armor type is 0-2"

### Armor Pickups (p_inter.c)

**P_GiveArmor()** (p_inter.c:252-266):
- Calculates `hits = armortype * 100` (line 258)
  - Type 1 → 100 points
  - Type 2 → 200 points
- Rejects pickup if player already has ≥ hits (line 259)
- Sets player→armortype and player→armorpoints to hits (lines 262-263)

**P_TouchSpecialThing()** armor cases (p_inter.c:369-398):
- **SPR_ARM1** (line 370): Calls P_GiveArmor(player, 1)
- **SPR_ARM2** (line 376): Calls P_GiveArmor(player, 2)
- **SPR_BON2** (line 391): Bonus item—increments armorpoints by 1, caps at 200, defaults armortype to 1 if none

### Damage Absorption (p_inter.c:854-869)

**Core Logic**:
```
if (player->armortype) {
    if (player->armortype == 1)
        saved = damage/3;      // Type 1 saves 1/3 of damage
    else
        saved = damage/2;      // Type 2 saves 1/2 of damage
    
    if (player->armorpoints <= saved) {
        saved = player->armorpoints;
        player->armortype = 0;  // Armor consumed, remove classification
    }
    player->armorpoints -= saved;
    damage -= saved;
}
player->health -= damage;
```

**Semantics**:
- Integer division (floor): damage/3 and damage/2 truncate
- Armortype=1 absorbs ⌊damage/3⌋; Type 2 absorbs ⌊damage/2⌋
- Armor is consumed (decrements armorpoints) until depleted
- Once armorpoints reach 0, armortype resets to 0 (no further absorption)
- Remaining damage (after armor absorption) reduces player health

## Summary

DOOM's armor system has **two armor classes** (types 1 and 2), each with distinct absorption rates:
- **Green Armor (Type 1)**: 100 points capacity, reduces incoming damage by ⌊damage/3⌋
- **Blue Armor (Type 2)**: 200 points capacity, reduces incoming damage by ⌊damage/2⌋

Armor pickups work via `P_TouchSpecialThing()`:
- ARM1 and ARM2 call `P_GiveArmor()`, which only grants the pickup if its value exceeds current armor
- BON2 increments armorpoints by 1, capping at 200, and defaults armortype to 1

When damage is taken, `P_DamageMobj()` applies the absorption formula **before** health loss:
1. Calculate saved = damage / armortype_multiplier (3 or 2)
2. Cap saved by remaining armorpoints
3. Deduct saved from both armorpoints and damage
4. Reduce player health by remaining damage
5. Zero armortype when armorpoints depleted

## Open Follow-ups

1. **Armor Bonus Behavior**: Does SPR_BON2 ever exceed armortype classification? (Can type 1 reach 200?)
2. **Fractional Damage**: How does integer division interact with repeated small-damage hits vs. single large hits?
3. **Megasphere Interaction**: Does the megasphere special case (p_inter.c:409-417) create any edge cases?
4. **Invulnerability Stacking**: Does invulnerability power completely bypass armor (p_inter.c:847-851)?
