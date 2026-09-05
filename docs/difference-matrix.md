# Difference Matrix — AltarSMP Original (S1/S2 spigot) vs Current Fabric 2.0.5 vs Bedrock deliverable

Legend — STATUS: `PARITY` current matches original; `REGRESSION` current changed behaviour vs original;
`BEDROCK-GAP` mechanically unexpressible on Bedrock/Geyser; `PACK-BREAK` broken in the reference pack itself.
REQUIRED ACTION references `AltarSMP-Custom-Content/documentation/MOD-PATCHES/` files (P0–P5) or none.

| # | FEATURE | ORIGINAL IMPLEMENTATION (Altar_SMPS1-2 jar + sources + RP) | CURRENT FABRIC 2.0.5 | STATUS | REQUIRED ACTION |
|---|---------|--------------------------------------------------------------|----------------------|--------|-----------------|
| 1 | Item/weapon registry | hand-written classes per item, PDC identity via NBT | JSON content registry (`altarsmp/content/*.json`) + `ItemFactory`/`Identity` | PARITY | none — Bedrock maps by (base material, CMD) harvested from both |
| 2 | Ability routing (main / offhand / crouch+offhand) | Bukkit listeners | Fabric events, identical routing semantics | PARITY | none — server-side, works for Bedrock inputs already |
| 3 | Custom item visuals | CMD-driven models, legacy `custom_models` | modern `items/*.json` dispatch (select/condition/range_dispatch/using_item/display_context/charge) | PARITY | converted: 72/72 variants → 72 bedrock defs (70 base + 2 crossbow charge-predicate variants; purple_harness/diamond_spear ship assets only, no mapping - fake java items) |
| 4 | Vulcan's Crossbow | CMD1; pull→loading3; loaded→loading3 | same (crossbow|1 states incl. pull/charge) | PARITY | charge states via `match:charge_type` predicate; draw-frame visuals = BEDROCK-GAP §1.1/1.2 |
| 5 | Pale Crossbow | CMD2 static pale model | same | PARITY | none |
| 6 | Illusion Wand / Frost Scythe | `using_item` swaps to wand2/frost2 models | same RP branches (netherite_sword 2/4) | PARITY + BEDROCK-GAP | using-state predicate unsupported (§1.1); idle visuals ship |
| 7 | Knightfall (mace) | CMD 15/16/17 kill-stage models | same | PARITY | none |
| 8 | Wither Symbiote | `display_context` split: hotbar sym (gui/ground/fixed) vs withersym (hand/head); altar shows PAPER|4 (AltarManager special-case) | same | BEDROCK-GAP | collapsed per §1.3 (icon=hotbarsym, geometry=withersym); mapped in display yml |
| 9 | Dragonrend | void-clock piece displays paper CMD 2/3/5 (+1 blue circle for CommandRegistrar hologram) | same | PARITY | all four converted + GDE entries |
| 10 | Tidebreaker | rising-tide water trident display (trident CMD1) | same | PARITY | converted + GDE entry |
| 11 | Crazy Slots | clay_ball CMD 4 + GUI menu (minor) | same | PARITY | converted; GUI uses server-side item comps |
| 12 | Relic shard (heavy_core markers) | CMD 998 relic_core / 999 block/clear invisible | same | PACK-BREAK | 998→vanilla fallback both sides; 999→zero-cube invisible geometry shipped |
| 13 | Contagion signal | stripped_crimson_hyphae CMD1 → custom/contagion_signal (25 elements, own display), parent block/stairs absent | same | PACK-BREAK | converted with missing-parent-as-empty (renders exactly like the Java pack's own elements) |
| 14 | Copper armour (netherite set) | equippable `custom:copper` layer + CMD1 on netherite bases | same | PARITY | armor-layer attachables + equippable component + protection 3/3/3/3 parsed from lore |
| 15 | Copper armour (diamond set) | equippable layer, no CMD (vanilla held look both eras) | same | BEDROCK-GAP | P0 — add CMD1 hook so worn look can map on Bedrock (currently vanilla diamond there) |
| 16 | CopperPickaxe | NETHERITE_PICKAXE eff5/fort3/unbr10/mending + 3×3 vein mining | STONE base, null CMD, no vein mining | REGRESSION | P1 |
| 17 | FireSlash displays | ITEM displays clay_ball CMD 12/13 (fixed transform, 1.5/0.2 scale, brightness 15) — modern pack already dropped 12/13 dispatch | fire-wave = vanilla particles + sounds only | REGRESSION (+ BEDROCK-GAP display transforms) | P3 (restore needs spawns + new pack models; GDE does not sync server transforms) |
| 18 | Paladin shrapnel | clay_ball CMD 8 displays on hit | golden_sword/shield block displays | REGRESSION | current visuals converted+mapped; P4 to restore original |
| 19 | Omen | baseMaterial "DIAMOND_SPEAR" (invalid → MACE fallback), CMD1 | MACE CMD1 | PARITY | none — vanilla mace look both sides; pack's dead `items/diamond_spear.json` converted as asset, no mapping (fake java item) |
| 20 | PlayerTrackerItem | recovery_compass + CMD 2000 sentinel (no model branch in any era) | same | PARITY | none; P5 documents optional visual |
| 21 | Nuke launch | concrete/ice/glowstone/shield/… displays + nuke sounds | displays same set; plays raw id `custom/nuke_*` unregistered (silent Java) | REGRESSION (sound) | pack ships `custom.nuke_*` + `minecraft.*` alias keys; P2 makes them actually play on both sides |
| 22 | Bloodlust | feathers/nuggets CMD (bone→gold_nugget 8 / iron_nugget 9 resurface-upgrade), `custom:bloodlust.*` events | same but bloodlust events never existed in any sounds.json | PACK-BREAK | silent both sides; noted in missing-assets.txt |
| 23 | Altars (40 entries) | ITEM display floaters (various bases, mostly vanilla + some CMD items) | same via altars.json | PARITY | every altar entry with a mapped item carries a GeyserDisplayEntity yml row (5 custom + 10 vanilla pass-through; rest are plain vanilla items shown natively) |
| 24 | BoneBlade | bone CMD? + `bone` display shards (bone in hide-types would kill them) | same | PARITY | GDE config shipped with "bone" removed from hide-types |
| 25 | MythicWeapons asset set | 191 textures + 580 item defs incl. all S1 weapon models | 2.0.5 content only references 34 of the 580 | PARITY (orphan assets) | 546 orphan variants intentionally NOT mapped (no server item can emit them; would create dead bedrock items) |
| 26 | Particles | vanilla particle types only (no RP particles dir in any reference) | same | PARITY | Geyser maps vanilla particles natively; nothing to convert |
| 27 | Sounds (9 ogg + 11 keys) | mythicweapons 5, altarsmps2 2, nuke 2, + hv_dig events w/o files | same | PACK-BREAK (hv_dig) | all 9 shipped oggs + alias keys; hv_dig/bloodlust silent both sides documented |
| 28 | Tooltips (`tooltip_style`) | RP tooltip sprites (fire_slash etc.) | same sprites in jar | BEDROCK-GAP | no bedrock equivalent (§1.5); text lore via components is identical |
| 29 | Display-entity rotation/scale | server-set `Transformation` honoured by Java | GDE renders on armor-stand (fixed knobs) | BEDROCK-GAP | documented §4.1; per-type y-offset/hand options prewired in shipped yml |
| 30 | Vanilla look for CMD'd items w/o branch (amethyst 5/6 fallback, snowball ic/skull/redblock) | falls to missing/fallback models (pack's own bug) | same | PACK-BREAK | defs map CMDs without custom visual — identical fallback look; no placeholders invented |

**Net conversion result:** 72 required variants → 72 mapped (70 mapped base variants with converted custom visuals + 2 crossbow charge-predicate variants, 6 fallback-look mirrors of pack-internal breaks, 2 fake-item definitions converted as assets only). Build/live-test status and unverifiable claims: see DIFFERENCES.txt §5.4 — sandbox had no JDK/network, so gradle build, server boot and live dual-client tests were NOT executed; static validation (tools/validator) is the acceptance gate used here.
