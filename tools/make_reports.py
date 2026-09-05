#!/usr/bin/env python3
"""Compose validation/ reports + documentation inventories from catalog + build report."""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEL = ROOT / "AltarSMP-Custom-Content"

cat = json.load(open(ROOT / "docs/catalog/custom-items.json", encoding="utf-8"))
rep = json.load(open(DEL / "tools/build-report.json", encoding="utf-8"))
maps = json.load(open(DEL / "custom_mappings/geyser_item_mappings.json", encoding="utf-8"))
atlas = json.load(open(DEL / "pack_source/textures/item_texture.json", encoding="utf-8"))

# ---------------- parity report (per required variant)
variants = []
for key, e in sorted(cat["items"].items()):
    item, cmd = e["java_item"], e["cmd"]
    defs = [d for it, dl in maps["items"].items() if it == item for d in dl if d.get("custom_model_data") == cmd]
    states = e["states"]
    sub = [v for k, v in rep["emitted"].items() if k.startswith(f"{item}|{cmd}::")]
    variants.append({
        "java_item": item, "cmd": cmd,
        "java_states": {s: (st.get("model") or "builtin") for s, st in sorted(states.items())},
        "contexts": e.get("contexts", []),
        "missing_refs": e.get("missing_refs", []),
        "bedrock_defs": [{"identifier": d["bedrock_identifier"],
                          "icon": (d.get("bedrock_options") or {}).get("icon"),
                          "predicate": d.get("predicate"),
                          "components": sorted((d.get("components") or {}).keys())} for d in defs],
        "emitted": [{"slug_id": v.get("bedrock_identifier"), "geometry": bool(v.get("note")) and True,
                     "note": v.get("note"), "no_textures": v.get("no_textures"),
                     "unexpressible_states": v.get("unexpressible_states")} for v in sub],
        "mapping_count": len(defs),
        "status": "converted" if defs and not any(v.get("no_textures") for v in sub) else
                  ("converted-fallback-visual" if defs else "UNMAPPED"),
    })

n_conv = sum(1 for v in variants if v["status"] == "converted")
n_fb = sum(1 for v in variants if v["status"] == "converted-fallback-visual")
n_un = sum(1 for v in variants if v["status"] == "UNMAPPED")

parity = {
    "generated": str(date.today()),
    "inputs": {
        "fabric_jar": "altarsmp-fabric-2.0.5.jar",
        "fabric_sources": "altarsmp-fabric-2.0.5-sources.jar",
        "original_jar": "Altar_SMPS1-2 (1).jar", "original_sources": "Altar_SMPS1-2-sources-FRESH.jar",
        "original_resource_pack": "AltarSMP-ResourcePack.zip"},
    "counts": {
        "items_discovered": cat["meta"]["counts"]["mod_items"],
        "weapons": cat["meta"]["counts"]["mod_weapons"],
        "armor": cat["meta"]["counts"]["mod_armor"],
        "altar_entries": cat["meta"]["counts"]["mod_altar_entries"],
        "java_item_model_definitions": cat["meta"]["counts"]["item_model_definitions"],
        "item_command_sites": cat["meta"]["counts"]["item_commands_used"],
        "required_cmd_variants": len(variants),
        "bedrock_definitions_emitted": sum(len(v) for v in maps["items"].values()),
        "mapped_java_items": len(maps["items"]),
        "unique_bedrock_identifiers": len({d["bedrock_identifier"] for dl in maps["items"].values() for d in dl}),
        "geometries": len(list((DEL / "pack_source/models").glob("*.geo.json"))),
        "attachables": len(list((DEL / "pack_source/attachables").glob("*.json"))),
        "animations": len(list((DEL / "pack_source/animations").glob("*.json"))),
        "render_controllers": len(list((DEL / "pack_source/render_controllers").glob("*.json"))),
        "item_texture_tiles": len(atlas["texture_data"]),
        "texture_files": len(list((DEL / "pack_source/textures/items/altarsmp").rglob("*.png"))),
        "copied_source_textures": rep["stats"]["textures"],
        "flipbooks": rep["stats"]["flipbooks"],
        "sound_events": len(rep.get("sound_keys", [])),
        "sound_files": rep["stats"]["sounds"],
        "gde_display_entries": rep.get("gde_entries", 0),
        "variants_fully_converted": n_conv,
        "variants_fallback_visual": n_fb,
        "variants_unmapped": n_un,
    },
    "variants": variants,
    "unmapped_usage_vanilla_parity": rep.get("unmapped_usage", []),
    "warnings": rep.get("warnings", []),
}
(DEL / "validation/parity-report.json").write_text(json.dumps(parity, indent=1), encoding="utf-8")

# txt summary
L = [f"AltarSMP 2.0.5 -> Bedrock parity report ({date.today()})", "=" * 60, ""]
for k, v in parity["counts"].items():
    L.append(f"{k:>34}: {v}")
L += ["", f"{'variant':<44} {'status':<28} defs  bedrock id"]
for v in variants:
    bid = v["bedrock_defs"][0]["identifier"] if v["bedrock_defs"] else "-"
    L.append(f"{v['java_item'].replace('minecraft:','')+'|'+str(v['cmd']):<44} {v['status']:<28} {v['mapping_count']:>3}  {bid}")
L += ["", "unmapped usage (vanilla look both sides):"]
for u in rep.get("unmapped_usage", []):
    L.append(f"  {u['java_item']}|{u['cmd']}  <- {', '.join(u['contexts'][:2])}")
(DEL / "validation/parity-report.txt").write_text("\n".join(L) + "\n", encoding="utf-8")

# missing assets file: pack-intrinsic breaks + source-pack missing refs
M = ["Assets referenced by the ORIGINAL resource pack / current mod but absent from every reference file.",
     "These cannot be fabricated without placeholders; bedrock mirrors Java behaviour (vanilla fallback).",
     "", "Referenced but absent models (pack-internal breaks, pre-existing in AltarSMP-ResourcePack.zip):"]
seen = set()
for w in rep.get("warnings", []):
    if "no textures" in w:
        M.append("  - " + w)
        seen.add(w.split("model ")[1].split(" has")[0])
for u in rep.get("unmapped_usage", []):
    pass
M += ["", "Absent from the pack but provided by the vanilla client jar (Java renders them; Bedrock shows base-item look):",
      "  - minecraft:block/heavy_core (model+texture) — clay_ball|1 relic shard marker",
      "  - minecraft:item/breeze_rod (model+texture) — clay_ball|2",
      "  - minecraft:item/sculk-family textures — resolved via pack copy 'item/scuk' (shipped)"]
M += ["", "Sound events declared in pack sounds.json but with no ogg in any reference file (silent on both sides):"]
for w in rep.get("warnings", []):
    if "sound event" in w:
        M.append("  - " + w.split(": ", 1)[-1])
M += ["", "Sound identifiers played by the mod that resolve to no Java event (silent on Java too):",
      "  - custom:bloodlust.resurface, custom:bloodlust.dive (BloodlustWeapon — no sounds.json entry anywhere)",
      "  - custom/nuke_incoming, custom/nuke_explosion as raw ids (event exists as minecraft:custom.nuke_incoming;",
      "    pack ships 'custom.nuke_incoming' + 'minecraft.custom.nuke_incoming' keys; see MOD-PATCHES note to",
      "    change the mod to play the event id so the alarm actually sounds on both sides)"]
(DEL / "validation/missing-assets.txt").write_text("\n".join(M) + "\n", encoding="utf-8")

print("parity variants:", len(variants), "conv:", n_conv, "fb:", n_fb, "un:", n_un)
