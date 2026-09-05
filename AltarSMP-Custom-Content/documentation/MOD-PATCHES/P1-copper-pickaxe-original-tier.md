# P1 — restore CopperPickaxe to original S1 material + vein mining

Original (`com/altarsmp/items/CopperPickaxe.java`): NETHERITE_PICKAXE,
Efficiency 5, Fortune 3, Unbreakable 10, Mending, plus 3x3 vein-mining of
copper/ores via a block-break listener.
Current 2.0.5: STONE base material, null CMD, no vein handler.

Bedrock impact: mirror-of-current (vanilla stone look; stats are server-side
and identical on both sides). The difference to restore is **stats + vein
mining**, not visuals — no pack model branch is tied to the original.

Action: port the original builder + `PlayerBlockBreakEvent` vein set into
`fabric/item`, or record the regression as intentional.
