"""
Static analysis of the CURRENT Fabric 2.0.5 sources: derive every (java base item,
custom model data) pair the server can actually put into an inventory, onto a
display entity, or into a GUI, plus armor equippable models, sounds and commands.

Sources of truth (in order of authority):
  1. altarsmp/content/{weapons_s1,weapons_s2,items,armor}.json  - declarative content
  2. altarsmp/content/altars.json                                - altar floating displays
  3. regex scan of every .java file for applyModelData/Items.X patterns - special VFX items
"""

import json
import os
import re
from pathlib import Path

BUKKIT_TO_MC = {  # small map for materials that differ in naming; others lower-case 1:1
    "NETHERITE_SWORD": "netherite_sword", "NETHERITE_AXE": "netherite_axe",
    "NETHERITE_PICKAXE": "netherite_pickaxe", "NETHERITE_HELMET": "netherite_helmet",
    "NETHERITE_CHESTPLATE": "netherite_chestplate", "NETHERITE_LEGGINGS": "netherite_leggings",
    "NETHERITE_BOOTS": "netherite_boots", "PLAYER_HEAD": "player_head",
    "GOLD_BLOCK": "gold_block", "REDSTONE_BLOCK": "redstone_block",
    "NETHER_STAR": "nether_star", "COPPER_INGOT": "copper_ingot",
    "COPPER_BLOCK": "copper_block", "HEAVY_CORE": "heavy_core",
    "ECHO_SHARD": "echo_shard", "GOLD_NUGGET": "gold_nugget", "IRON_NUGGET": "iron_nugget",
    "AMETHYST_SHARD": "amethyst_shard", "RECOVERY_COMPASS": "recovery_compass",
    "SNOWBALL": "snowball", "CLAY_BALL": "clay_ball", "FEATHER": "feather",
    "PAPER": "paper", "DRAGON_HEAD": "dragon_head", "BREEZE_ROD": "breeze_rod",
    "TRIDENT": "trident", "CROSSBOW": "crossbow", "BOW": "bow", "MACE": "mace",
    "PALE_LOGS": "pale_logs", "STRIPPED_CRIMSON_HYPHAE": "stripped_crimson_hyphae",
    "RED_CONCRETE": "red_concrete", "BARRIER": "barrier", "STONE": "stone",
    "DIAMOND_HELMET": "diamond_helmet", "DIAMOND_CHESTPLATE": "diamond_chestplate",
    "DIAMOND_LEGGINGS": "diamond_leggings", "DIAMOND_BOOTS": "diamond_boots",
    "ELYTRA": "elytra", "LEATHER_HORSE_ARMOR": "leather_horse_armor",
    "SKELETON_SKULL": "skeleton_skull", "WITHER_SKELETON_SKULL": "wither_skeleton_skull",
    "COD_BUCKET": "cod_bucket", "LIME_DYE": "lime_dye", "COMPASS": "compass",
}


def mc_item(material):
    if material is None:
        return None
    m = str(material).upper()
    if m in BUKKIT_TO_MC:
        return BUKKIT_TO_MC[m]
    return m.lower()


def load_content(fabsrc):
    fab = Path(fabsrc)
    out = {}
    for key, fn in [("weapons_s1", "weapons_s1.json"), ("weapons_s2", "weapons_s2.json"),
                    ("items", "items.json"), ("armor", "armor.json"),
                    ("altars", "altars.json"), ("recipes", "recipes.json"),
                    ("ingredients", "ingredients.json")]:
        p = fab / "altarsmp" / "content" / fn
        out[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return out


def scan_java(fabsrc):
    """Regex sweep of the fabric sources for item/model/sound usage."""
    fab = Path(fabsrc)
    hits = {"applyModelData": [], "items_material": {}, "sounds": [], "head_items": []}
    mat_re = re.compile(r"Items\.([A-Z0-9_]+)")
    model_re = re.compile(r"applyModelData\(\s*([A-Za-z0-9_.]+)\s*,\s*([A-Za-z0-9_+\- ]+?)\s*\)")
    newstack_re = re.compile(r"new ItemStack\(Items\.([A-Z0-9_]+)(?:[^)]*\))?")
    cmd_const_re = re.compile(r"(?:static final int|int)\s+([A-Z_0-9]+)\s*=\s*(\d+)\s*;")
    sound_re = re.compile(r"Fx\.sound(?:To|At)?\(\s*[^,]+,\s*(?:[^,]+,\s*)?\"([a-z0-9_./]+)\"")
    sound_id_re = re.compile(r"Identifier\.fromNamespaceAndPath\(\"(altarsmps2|mythicweapons|altarsmp)\",\s*\"([a-z0-9_./]+)\"\)")
    id_str_re = re.compile(r"Fx\.sound(?:To|At)?\([^;]*?\"(custom/[a-z0-9_./]+)\"")
    consts_by_file = {}
    for dp, _, fns in os.walk(fab):
        for fn in fns:
            if not fn.endswith(".java"):
                continue
            p = os.path.join(dp, fn)
            txt = open(p, encoding="utf-8", errors="replace").read()
            consts = {}
            for m in cmd_const_re.finditer(txt):
                consts[m.group(1)] = int(m.group(2))
            consts_by_file[p] = consts
            rel = os.path.relpath(p, fab)
            for m in model_re.finditer(txt):
                target, expr = m.group(1), m.group(2).strip()
                val = None
                if re.fullmatch(r"-?\d+", expr):
                    val = int(expr)
                elif expr in consts:
                    val = consts[expr]
                mats = mat_re.findall(txt)
                hits["applyModelData"].append({
                    "file": rel, "target": target, "expr": expr, "value": val,
                    "items_seen": sorted(set(mats))[:12],
                })
            for m in sound_re.finditer(txt):
                hits["sounds"].append((rel, m.group(1)))
            for m in sound_id_re.finditer(txt):
                hits["sounds"].append((rel, f"{m.group(1)}/{m.group(2)}"))
            for m in id_str_re.finditer(txt):
                hits["sounds"].append((rel, m.group(1)))
    return hits


def build_usage_map(content, hits):
    """
    Complete set of (mc_item, cmd) pairs the server can emit + context (who/why).
    """
    uses = {}

    def add(item, cmd, ctx):
        if item is None:
            return
        uses.setdefault((item, cmd), []).append(ctx)

    for wk in ("weapons_s1", "weapons_s2"):
        for w in content[wk] or []:
            add(mc_item(w.get("base_material")), w.get("custom_model_data"), f"weapon:{w.get('id')}")
    for it in content["items"] or []:
        add(mc_item(it.get("base_material")), it.get("custom_model_data"), f"item:{it.get('class')}")
    for a in content["armor"] or []:
        add(mc_item(a.get("base_material")), a.get("custom_model_data"), f"armor:{a.get('id', a.get('class'))}")

    altars = content["altars"] or {}
    for season in ("season1", "season2"):
        for a in altars.get(season, []):
            mat = a.get("material")
            cmd = a.get("cmd")
            if a.get("display") == "Wither Symbiote":
                mat, cmd = "PAPER", 4  # AltarManager special case
            add(mc_item(mat), cmd, f"altar:{season}:{a.get('display')}")

    # Special VFX items wired directly in code (not through ContentCatalog).
    # Each entry cites its current-source evidence file:line so the parity docs can
    # point at the call site. Discovered by scanning every Displays.* call site.
    SPECIAL = [
        ("paper", 1, "blue-circle hologram — command/CommandRegistrar.java:1770 (BLUE_CIRCLE_MODEL=1)"),
        ("paper", 2, "dragonrend clock void clock — weapon/s2/DragonrendWeapon.java voidClockPiece(2)"),
        ("paper", 3, "dragonrend short arrow — weapon/s2/DragonrendWeapon.java voidClockPiece(3)"),
        ("paper", 5, "dragonrend tall arrow — weapon/s2/DragonrendWeapon.java voidClockPiece(5)"),
        ("trident", 1, "tidebreaker rising-tide water trident — weapon/s2/TidebreakerWeapon.java:214"),
    ]
    for item, cmd, ctx in SPECIAL:
        add(item, cmd, ctx)

    # Plain (no-CMD) display entities the extension must still show on Bedrock.
    vanilla_display_items = [
        "bone", "bone_block", "golden_sword", "shield", "glowstone", "ice",
        "nether_star", "carved_pumpkin", "splash_potion", "netherite_sword",
    ]
    return uses, hits, vanilla_display_items
