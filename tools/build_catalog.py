"""
Phase 4/5 — complete custom-item database.

Derives (not hardcodes) every custom item and every CustomModelData variant from:
  * the resource pack item definitions (all namespaces, full dispatch trees),
  * the current Fabric 2.0.5 content catalog (weapons/items/armor/altars),
  * code-level display-item call sites in the current sources,
and resolves each (java item, CMD) pair through Java range-dispatch semantics to the
model(s) the Java client renders in each state (idle / using / gui / ground / fixed /
charge / pull), including every model dependency (parents, textures).

Output: docs/catalog/custom-items.json (+ human-readable txt summary).
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from altarbedrock import java_rp, modscan  # noqa: E402


def texture_refs(rp, model_id):
    m = rp.resolve_model(model_id)
    textures = {}
    for slot, tid in m["textures"].items():
        p = rp.texture_path(tid)
        textures[slot] = {
            "id": tid,
            "path": os.path.relpath(p, rp.root).replace("\\", "/"),
            "exists": p.exists(),
            "size": list(java_rp.png_size(p)) if p.exists() else None,
        }
    return textures, m


def element_count(m):
    return len(m["elements"])


def model_is_flat(m):
    """generated-style model: <=2 element cubes OR every element is a single 1-sided quad plane."""
    els = m["elements"]
    if not els:
        return True
    for el in els:
        fr, to = el.get("from", [0, 0, 0]), el.get("to", [0, 0, 0])
        thin = [abs(to[i] - fr[i]) for i in range(3)]
        if len(el.get("faces", {})) > 2:
            return False
        if sum(1 for t in thin if t > 0.01) > 2:  # box with volume-ish
            return False
    return True


def all_definitions(rp):
    out = {}
    for ns, name in rp.iter_definitions():
        loc = f"{ns}:{name}"
        data = rp.load_json(rp.definition_path(loc))
        out[loc] = data
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rp", required=True, help="extracted AltarSMP-ResourcePack root")
    ap.add_argument("--fabsrc", required=True, help="extracted altarsmp-fabric-2.0.5-sources root")
    ap.add_argument("--origsrc", help="extracted original sources (for difference matrix)")
    ap.add_argument("--out", default="docs/catalog")
    args = ap.parse_args()

    rp = java_rp.JavaRP(args.rp)
    defs = all_definitions(rp)
    content = modscan.load_content(args.fabsrc)
    uses, hits, vanilla_disp = modscan.build_usage_map(content, modscan.scan_java(args.fabsrc))

    walker = java_rp.DispatchWalker(rp)

    # 1) collect the union of CMD branches from every definition in the pack
    cmd_branches = {}   # java item -> {cmd: branch model node}
    for loc, data in defs.items():
        if not data or "__error__" in data or loc.split(":")[0] not in ("minecraft", "custom"):
            continue
        variants = walker.all_cmd_variants(data)
        if variants:
            cmd_branches.setdefault(loc, {}).update(variants)

    # 2) every (item,cmd) the MOD can emit + every CMD the pack dispatch declares
    required = dict(uses)
    for item, branches in cmd_branches.items():
        for cmd in branches:
            required.setdefault((item, cmd), ["rp-dispatch"])

    # for (item,cmd) where cmd not an exact threshold, resolve via greatest-threshold<=cmd
    # and also ensure the exact cmd gets its own mapping entry (legacy defs are exact-match)
    resolved_pairs = set()
    for (item, cmd) in list(required.keys()):
        branches = cmd_branches.get(item, {})
        if cmd is None:
            continue
        hit = None
        for thr in sorted(branches):
            if thr <= cmd:
                hit = thr
        if hit is None:
            # no dispatch -> item renders vanilla on Java too -> record but no bedrock custom needed
            required[(item, cmd)].append("no-rp-branch->vanilla-parity")
            continue
        resolved_pairs.add((item, cmd, hit))

    catalog = {}
    for (item, cmd, branch_thr) in sorted(resolved_pairs):
        branch = cmd_branches[item][branch_thr]
        states = walker.states_of_branch(branch)
        models = {}
        missing = []
        for name, model in states:
            if model is None:
                continue
            tex, m = texture_refs(rp, model)
            missing += [f"{name}: {x}" for x in m["missing"]]
            models[name] = {
                "model": model,
                "flat": model_is_flat(m),
                "elements": element_count(m),
                "textures": tex,
                "display": m["display"],
                "gui_light": m["gui_light"],
                "texture_size": m["texture_size"],
                "roots": m["roots"],
            }
        key = f"{item}|{cmd}"
        catalog[key] = {
            "java_item": item,
            "cmd": cmd,
            "dispatch_branch_threshold": branch_thr,
            "contexts": sorted(set(required[(item, cmd)])),
            "states": models,
            "missing_refs": missing,
        }

    # 3) every declared dispatch variant across the whole pack (parity audit incl. unused)
    pack_variants = {}
    for item, branches in sorted(cmd_branches.items()):
        for cmd in sorted(branches):
            key = f"{item}|{cmd}"
            if key in catalog:
                catalog[key]["contexts"].append(f"pack-declared:{cmd}")
                continue
            states = walker.states_of_branch(branches[cmd])
            models = {}
            for name, model in states:
                if not model:
                    continue
                tex, m = texture_refs(rp, model)
                models[name] = {
                    "model": model, "flat": model_is_flat(m),
                    "elements": element_count(m), "textures": tex,
                    "display": m["display"], "gui_light": m["gui_light"],
                    "texture_size": m["texture_size"], "roots": m["roots"],
                }
            pack_variants[key] = {"java_item": item, "cmd": cmd,
                                  "contexts": ["pack-declared-only"], "states": models}

    # 4) model definitions that only exist via item_model (mythicweapons/items + mace lv defs etc.)
    item_model_defs = {}
    for loc, data in defs.items():
        if data and "__error__" not in data:
            model = walker.model_of(data.get("model", {}))
            item_model_defs[loc] = {"direct_model": model,
                                   "type": (data.get("model", {}) or {}).get("type", "minecraft:model")}

    out = Path(args.out)
    os.makedirs(out, exist_ok=True)
    payload = {
        "meta": {
            "generated_from": {"rp": str(args.rp), "fabsrc": str(args.fabsrc)},
            "counts": {
                "mod_items": len(content["items"] or []),
                "mod_weapons": len(content["weapons_s1"] or []) + len(content["weapons_s2"] or []),
                "mod_armor": len(content["armor"] or []),
                "mod_altar_entries": sum(len((content["altars"] or {}).get(k, [])) for k in ("season1", "season2")),
                "item_commands_used": sum(1 for _, v in required.items() for _ in v),
                "required_cmd_variants": len(catalog),
                "pack_declared_variants": len(pack_variants),
                "item_model_definitions": len(item_model_defs),
                "vanilla_display_items": vanilla_disp,
            },
        },
        "items": catalog,
        "pack_only_variants": pack_variants,
        "item_model_definitions": item_model_defs,
    }
    (out / "custom-items.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

    c = payload["meta"]["counts"]
    print("custom-items.json written to", out)
    print(json.dumps(c, indent=1))


if __name__ == "__main__":
    main()
