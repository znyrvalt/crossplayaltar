"""
Top-level build: reads catalog + content + sources, drives Builder, writes the full
deliverable payload (pack_source, packs/pack.zip, custom_mappings, lang, GDE template,
build report). Run via  python3 -m altarbedrock.build  (see tools/build.py wrapper).
"""

import json
import re
import shutil
import zipfile
from pathlib import Path

from . import modscan
from .genpack import Builder, slugify, bsafe, plain

ARMOR_SLOTS = {"helmet": "minecraft:head", "chestplate": "minecraft:chest",
               "leggings": "minecraft:legs", "boots": "minecraft:feet"}
HOLD_BASES = {"bow", "crossbow", "trident", "mace", "spear", "sword", "axe",
              "pickaxe", "shovel", "hoe", "fishing_rod", "carrot_on_a_stick", "warped_fungus_on_a_stick"}


def armor_protection_from_lore(lore):
    for line in lore or []:
        m = re.search(r"\+(\d+)\s+Armor(?![\s\S]*Toughness)", line)
        if m:
            return int(m.group(1))
    for line in lore or []:
        m = re.search(r"\+(\d+) Armor\b", line)
        if m:
            return int(m.group(1))
    return None


def run(rp_root, fab_root, fabsrc_root, deliverable, catalog_path,
         gde_repo=None, gde_extract=None, version="2.0.5"):
    deliverable = Path(deliverable)
    catalog = json.load(open(catalog_path, encoding="utf-8"))
    b = Builder(rp_root, fab_root, fabsrc_root, deliverable, catalog, version=version)

    content = modscan.load_content(fabsrc_root)
    hits = modscan.scan_java(fabsrc_root)
    usage, hits, vanilla_display = modscan.build_usage_map(content, hits)

    # ---- content index: (mc_item, cmd) -> meta  (keys namespaced to match the catalog)
    def pair(item, cmd):
        if item and ":" not in item:
            item = "minecraft:" + item
        return (item, cmd)
    idx = {}
    for wk in ("weapons_s1", "weapons_s2"):
        for w in content[wk] or []:
            item = modscan.mc_item(w.get("base_material"))
            idx[pair(item, w.get("custom_model_data"))] = {
                "kind": "weapon", "id": w.get("id"), "name": plain(w.get("display_name") or w.get("plain_display"))}
    for it in content["items"] or []:
        item = modscan.mc_item(it.get("base_material"))
        idx[pair(item, it.get("custom_model_data"))] = {
            "kind": "item", "id": it.get("class"), "name": plain(it.get("display_name"))}
    for a in content["armor"] or []:
        item = modscan.mc_item(a.get("base_material"))
        idx[pair(item, a.get("custom_model_data"))] = {
            "kind": "armor", "id": a.get("id") or a.get("class"),
            "name": plain(a.get("display_name")),
            "protection": armor_protection_from_lore(a.get("lore")),
            "base_material": a.get("base_material"), "class": a.get("class")}

    # ---- emit one bedrock def per required catalog variant
    emitted_by_pair = {}
    for key, e in sorted(catalog["items"].items()):
        item, cmd = e["java_item"], e["cmd"]
        states = e["states"]
        idle = states.get("idle") or {}
        idle_model = idle.get("model")
        gui_model = (states.get("idle.ctx_gui") or {}).get("model")
        meta = idx.get((item, cmd), {})
        base = item.split(":")[-1]
        handheld = base in HOLD_BASES
        if not handheld and idle_model:
            m = b.resolved(idle_model)
            if any(str(r).split(":")[-1].endswith("handheld") for r in m["roots"]):
                handheld = True
        equippable = None
        protection = None
        if meta.get("kind") == "armor":
            which = base.split("_")[-1]
            if which in ARMOR_SLOTS:
                equippable = {"slot": ARMOR_SLOTS[which].split(":")[-1]}
                protection = meta.get("protection")
        slug = slugify(item, cmd)
        FAKE_JAVA_ITEMS = {"minecraft:purple_harness", "minecraft:diamond_spear"}
        res = b.emit_def(
            item, cmd, slug, idle_model,
            emit_mapping=item not in FAKE_JAVA_ITEMS,
            icon_model=gui_model if gui_model and gui_model != idle_model else None,
            handheld=handheld, equippable=equippable, protection=protection,
            display_name=None,   # Geyser translates the server-side name component already
            note=f"{meta.get('kind','pack')}:{meta.get('id','')}" + (f" gui={gui_model}" if gui_model and gui_model != idle_model else ""),
        )
        emitted_by_pair[(item, cmd)] = slug
        # charge-variant defs (crossbow mechanics: bedrock charge_type predicate)
        for ctype in ("arrow", "rocket"):
            st = states.get(f"idle.charge_{ctype}")
            if st and st.get("model") and st["model"] != idle_model:
                vs = slugify(item, cmd, f"_{ctype}")
                b.emit_def(item, cmd, vs, st["model"], handheld=handheld,
                           equippable=equippable, protection=protection,
                           predicate={"type": "match",
                                      "match": {"type": "charge_type", "value": ctype}},
                           note=f"{ctype}-charged visual (crossbow charge_type predicate)")
                res.setdefault("charge_defs", {})[ctype] = vs
        # non-expressible Java states recorded for the difference report
        lossy = []
        for name in states:
            if name == "idle" or name in ("idle.ctx_gui", "idle.ctx_ground", "idle.ctx_fixed") \
               or name in ("idle.charge_arrow", "idle.charge_rocket"):
                continue
            st = states[name]
            if st.get("model") and st["model"] != idle_model:
                if name.startswith("idle.using"):
                    lossy.append(name)
        if lossy:
            res["unexpressible_states"] = sorted(set(lossy))

    # ---- pack-declared superset (CMDs the Java RP declares but the mod does not use)
    packonly_notes = []
    po = catalog.get("pack_only_variants") or {}
    for key, e in sorted(po.items()):
        item = e.get("java_item") or key.split("|")[0]
        cmd = e.get("cmd", key.split("|")[1] if "|" in key else None)
        try:
            cmd = int(cmd)
        except Exception:
            packonly_notes.append(f"{key}: cmd not int, skipped")
            continue
        if (item, cmd) in emitted_by_pair:
            continue
        states = e.get("states") or {}
        idle_model = (states.get("idle") or {}).get("model")
        m = b.resolved(idle_model) if idle_model else {"elements": [], "textures": {}, "roots": [], "missing": ["no model"]}
        if not m["elements"]:
            packonly_notes.append(f"{item}|{cmd}: model {idle_model} unresolvable in source pack — excluded (matches broken Java behaviour)")
            continue
        b.emit_def(item, cmd, slugify(item, cmd), idle_model,
                   handheld=base in HOLD_BASES, note="pack-declared variant (no current mod usage; Java-RP superset)")
        emitted_by_pair.setdefault((item, cmd), slugify(item, cmd))

    # ---- usage pairs the mod applies CMD to but the Java RP gives no branch for:
    #      these render the vanilla item look on BOTH sides -> no mapping needed (parity).
    unmapped_usage = []
    for (item, cmd), ctxs in sorted(usage.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        if (item, cmd) not in emitted_by_pair:
            unmapped_usage.append({"java_item": item, "cmd": cmd,
                                   "contexts": [str(c) for c in ctxs],
                                   "resolution": "vanilla look both sides (no RP dispatch); Geyser translates normally"})
    b.unmapped_usage = unmapped_usage

    # ---- armor equipment layers (vanilla armor geo + copied copper textures)
    armor_pairs = {}
    for (item, cmd), meta in idx.items():
        if meta.get("kind") == "armor" and emitted_by_pair.get((item, cmd)):
            base = item.split(":")[-1]
            armor_pairs[base] = (f"altarsmp:{emitted_by_pair[(item, cmd)]}", emitted_by_pair[(item, cmd)])
    b.emit_armor_layers(content["armor"] or [], armor_pairs)

    # ---- GeyserDisplayEntity display mappings (item displays the server spawns)
    b.gde = []
    for (item, cmd), ctxs in sorted(usage.items(), key=lambda kv: (str(kv[0]), str(kv[1]))):
        disp_ctxs = [c for c in ctxs if str(c).startswith("altar:")]
        slug = emitted_by_pair.get((item, cmd))
        if slug and disp_ctxs:
            b.gde.append({
                "key": f"altar_{item.split(':')[-1]}_{cmd}",
                "type": f"minecraft:{item.split(':')[-1]}",
                "model-data": cmd,   # legacy format: GDE resolves via geyser custom-item mapping
                "displayentityoptions": {"y-offset": -0.5, "hand": False},
            })
    for vitem in vanilla_display:
        b.gde.append({
            "key": f"vanilla_{vitem}",
            "type": f"minecraft:{vitem}",
            "item-identifier": f"minecraft:{vitem}",  # modern format: native bedrock item
            "displayentityoptions": {"y-offset": -0.5, "hand": False},
        })
    b.vanilla_display = vanilla_display

    # ---- VFX item displays (blue circle / void clock / rising tide) -> GDE entries via
    #      the special table below (call sites documented there).
    # specials that definitely spawn item displays (documented call sites)
    vfx_specials = [
        ("minecraft:paper", 1), ("minecraft:paper", 2), ("minecraft:paper", 3),
        ("minecraft:paper", 5), ("minecraft:trident", 1),
    ]
    for item, cmd in vfx_specials:
        slug = emitted_by_pair.get((item, cmd))
        if slug and not any(g.get("model-data") == cmd and g["type"] == f"minecraft:{item.split(':')[-1]}" for g in b.gde):
            b.gde.append({
                "key": f"vfx_{item.split(':')[-1]}_{cmd}",
                "type": f"minecraft:{item.split(':')[-1]}",
                "model-data": cmd,   # legacy format (resolves via geyser mapping)
                "displayentityoptions": {"y-offset": -0.5, "hand": False},
            })

    # ---- sounds
    b.emit_sounds()

    # ---- write everything
    b.write_pack()
    b.write_mappings(deliverable / "custom_mappings")
    b.write_lang(deliverable / "lang")
    pack_zip = deliverable / "packs" / "pack.zip"
    pack_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pack_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(b.pack.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(b.pack))
    # GeyserDisplayEntity extension + data template
    if gde_repo and Path(gde_repo).exists():
        dst = deliverable / "extensions" / "GeyserDisplayEntity"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(gde_repo, dst, ignore=shutil.ignore_patterns(".git"))
    gde_dir = deliverable / "extensions" / "GeyserDisplayEntity-data"
    (gde_dir / "Mappings").mkdir(parents=True, exist_ok=True)
    cfg = {
        "general": {"height": 1.7, "y-offset": -0.5, "vanilla-scale": False,
                    "vanilla-scale-multiplier": 1.0, "hand": False},
        "hide-types": ["leather_horse_armor"],
        "hide-custom-types": [],
        "hide-unmapped-vanilla-displays": False,
        "settings": {"debug": False},
    }
    (gde_dir / "config.yml").write_text(yaml_dump(cfg), encoding="utf-8")
    lines = ["# AltarSMP display-entity mappings for GeyserDisplayEntity",
             "# generated from the Fabric 2.0.5 source usage map + catalog; do not hand-edit",
             "mappings:"]
    for g in b.gde:
        lines.append(f"  {g['key']}:")
        lines.append(f"    type: \"{g['type']}\"")
        if g.get("model-data", None) is not None:
            lines.append(f"    model-data: {g['model-data']}")
        if g.get("item-identifier"):
            lines.append(f"    item-identifier: \"{g['item-identifier']}\"")
        o = g.get("displayentityoptions") or {}
        if o:
            lines.append("    displayentityoptions:")
            for k, v in o.items():
                lines.append(f"      {k}: {json.dumps(v)}")
    (gde_dir / "Mappings" / "altarsmp-displays.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = {"stats": b.stats, "warnings": b.warnings,
              "pack_only_notes": packonly_notes,
              "unmapped_usage": unmapped_usage,
              "emitted": {k: v for (k, v) in b.report.items()},
              "sound_keys": getattr(b, "sound_keys", []), "sound_files": getattr(b, "sound_files", []),
              "gde_entries": len(b.gde),
              "usage_pairs": sorted(f"{i}|{c}" for (i, c) in usage)}
    json.dump(report, open(deliverable / "tools" / "build-report.json", "w"), indent=1)
    json.dump({"mappings_items": b.mappings_items, "item_texture": b.item_atlas,
               "lang": b.lang, "flipbooks": b.flip_tiles, "raw_flips": b.flip_raw},
              open(deliverable / "tools" / "gen-state.json", "w"), indent=1)
    return b, report


def yaml_dump(d, indent=0):
    out = []
    pad = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out.append(yaml_dump(v, indent + 1))
        elif isinstance(v, list):
            if v and all(not isinstance(x, (dict, list)) for x in v):
                out.append(f"{pad}{k}: [" + ", ".join(json.dumps(x) for x in v) + "]")
            else:
                out.append(f"{pad}{k}:")
                for x in v:
                    out.append(f"{pad}- {json.dumps(x)}")
        else:
            out.append(f"{pad}{k}: {json.dumps(v)}")
    return "\n".join(out)
