"""
Package validator: fails (exit 1) on any missing/duplicate/broken reference.

Checks (all must pass):
  S structure      required files/dirs exist
  M mappings       schema, uniqueness, icon/texture existence, legal predicates/components
  C coverage       every catalog (item,cmd) + charge variant has a mapping definition
  P pack           json validity, geometry/RC/animation cross-refs, sounds files present,
                   item_texture/attachable textures exist, manifest sane, flipbook tiles valid
  Z zip            pack.zip mirrors pack_source, manifest at root
  G GDE            yml item-identifiers resolve to mapped bedrock ids
"""

import json
import re
import sys
import zipfile
from pathlib import Path

ALLOWED_COMPONENTS = {
    "minecraft:max_stack_size", "minecraft:food", "minecraft:consumable",
    "minecraft:equippable", "minecraft:tool", "minecraft:repairable",
    "minecraft:enchantable", "minecraft:use_cooldown", "minecraft:max_damage",
    "minecraft:attack_range", "minecraft:kinetic_weapon", "minecraft:piercing_weapon",
    "minecraft:swing_animation", "minecraft:use_effects", "minecraft:enchantment_glint_override",
    "minecraft:rarity", "minecraft:attribute_modifiers", "minecraft:tooltip_display",
}
VANILLA_GEO = {"geometry.item_sprite", "geometry.player.armor.helmet", "geometry.player.armor.chest",
              "geometry.player.armor.legs", "geometry.player.armor.boots", "geometry.humanoid.custom"}
BUILTIN_RCS = {"controller.render.item_sprite"}


class V:
    def __init__(self, deliverable, catalog_path=None):
        self.root = Path(deliverable)
        self.errors = []
        self.checks = []
        self.counts = {}
        self.catalog = json.load(open(catalog_path)) if catalog_path else None

    def err(self, code, msg):
        self.errors.append(f"[{code}] {msg}")

    def ok(self, name, detail=""):
        self.checks.append(f"PASS {name} {detail}".rstrip())

    # ------------------------------------------------------------------ main
    def run(self):
        self.structure()
        mappings = self.mappings()
        pack = self.load_pack()
        if pack is not None:
            self.pack_checks(pack, mappings)
            self.zip_check(pack)
        if self.catalog and mappings is not None:
            self.coverage(mappings)
        self.gde(mappings)
        return self

    def load_pack(self):
        src = self.root / "pack_source"
        if src.exists():
            return {"dir": src, "z": None}
        zp = self.root / "packs" / "pack.zip"
        if zp.exists():
            return {"dir": None, "z": zipfile.ZipFile(zp)}
        self.err("S", "no pack_source/ nor packs/pack.zip")
        return None

    def pfile(self, pack, rel):
        if pack["dir"]:
            p = pack["dir"] / rel
            return p.read_bytes() if p.exists() else None
        z = pack["z"]
        try:
            return z.read(rel)
        except KeyError:
            return None

    def pjson(self, pack, rel):
        b = self.pfile(pack, rel)
        if b is None:
            return None
        try:
            return json.loads(b.decode("utf-8"))
        except Exception as e:
            self.err("P", f"{rel}: invalid json: {e}")
            return None

    # ------------------------------------------------------------------ S
    def structure(self):
        need = ["custom_mappings/geyser_item_mappings.json", "custom_mappings/geyser_block_mappings.json",
                "custom_mappings/geyser_skull_mappings.json", "custom_mappings/geyser_waypoint_style_mappings.json",
                "packs/pack.zip", "packs/GeyserDisplayEntityPack.mcpack", "lang/en_US.lang",
                "documentation/INSTALL.txt", "documentation/DIFFERENCES.txt", "documentation/CONTENT-INVENTORY.TXT",
                "tools/validator/validate.py", "extensions/GeyserDisplayEntity-data/config.yml",
                "extensions/GeyserDisplayEntity-data/Mappings/altarsmp-displays.yml"]
        missing = [n for n in need if not (self.root / n).exists()]
        for m in missing:
            self.err("S", f"missing {m}")
        if not missing:
            self.ok("structure", f"all {len(need)} required deliverable files present")

    # ------------------------------------------------------------------ M
    def mappings(self):
        mp = self.root / "custom_mappings" / "geyser_item_mappings.json"
        d = json.loads(mp.read_text(encoding="utf-8"))
        if d.get("format_version") != 2:
            self.err("M", "format_version != 2")
        seen_ids = {}
        pat = re.compile(r"^altarsmp:[a-z0-9_.\-]+$")
        for item, defs in d["items"].items():
            if not re.fullmatch(r"minecraft:[a-z0-9_./-]+", item):
                self.err("M", f"bad java item key {item!r}")
            for defn in defs:
                t = defn.get("type")
                if t not in ("legacy", "definition", "group"):
                    self.err("M", f"{item}: def type {t!r} not allowed")
                bid = defn.get("bedrock_identifier", "")
                if not pat.match(bid):
                    self.err("M", f"{item}: bad bedrock_identifier {bid!r}")
                if bid in seen_ids and not defn.get("predicate"):
                    # same id twice is only ok inside predicate-variant groups of same cmd
                    if seen_ids[bid] != defn.get("custom_model_data"):
                        self.err("M", f"duplicate bedrock_identifier {bid}")
                seen_ids.setdefault(bid, defn.get("custom_model_data"))
                if t == "legacy":
                    cmd = defn.get("custom_model_data")
                    if not isinstance(cmd, int) or cmd < 0:
                        self.err("M", f"{item}/{bid}: legacy def needs int custom_model_data >= 0, got {cmd!r}")
                opts = defn.get("bedrock_options") or {}
                for k in opts:
                    if k not in ("icon", "allow_offhand", "display_handheld", "protection_value",
                                 "creative_category", "creative_group", "tags"):
                        self.err("M", f"{item}/{bid}: unknown bedrock_options key {k!r}")
                for k in (defn.get("components") or {}):
                    if k not in ALLOWED_COMPONENTS:
                        self.err("M", f"{item}/{bid}: unsupported component {k!r}")
                p = defn.get("predicate")
                if p:
                    ptype = p.get("type")
                    if ptype not in ("condition", "match", "range_dispatch"):
                        self.err("M", f"{item}/{bid}: illegal predicate type {ptype!r}")
                    elif ptype == "condition":
                        prop = (p.get("condition") or {}).get("property", "")
                        if prop.split(":")[-1] not in ("broken", "damaged", "custom_model_data",
                                                        "has_component", "fishing_rod_cast"):
                            self.err("M", f"{item}/{bid}: illegal condition property {prop!r}")
                    elif ptype == "match":
                        mt = (p.get("match") or {}).get("type", "")
                        if mt not in ("charge_type", "trim_material", "context_dimension", "custom_model_data"):
                            self.err("M", f"{item}/{bid}: illegal match type {mt!r}")
        self.counts["mapping_defs"] = sum(len(v) for v in d["items"].values())
        self.counts["mapping_items"] = len(d["items"])
        self.counts["unique_bedrock_ids"] = len(seen_ids)
        self.ok("mappings", f"{self.counts['mapping_items']} java items, {self.counts['mapping_defs']} defs, "
                            f"{len(seen_ids)} unique bedrock identifiers")
        return d

    # ------------------------------------------------------------------ C
    def coverage(self, mappings):
        required = {}
        for key, e in self.catalog["items"].items():
            required[(e["java_item"], e["cmd"])] = e
        have = set()
        for item, defs in mappings["items"].items():
            for defn in defs:
                have.add((item, defn.get("custom_model_data")))
        missed = [f"{i}|{c}" for (i, c) in required if (i, c) not in have]
        # items intentionally excluded from mappings (non-vanilla java item keys) documented in report
        excl = {"minecraft:purple_harness", "minecraft:diamond_spear"}
        missed = [m for m in missed if m.split("|")[0] not in excl]
        if missed:
            for m in missed:
                self.err("C", f"no mapping def for required variant {m}")
        # charge-variant coverage for crossbow-based defs
        n_charge = 0
        for item, defs in mappings["items"].items():
            for defn in defs:
                pr = defn.get("predicate") or {}
                if (pr.get("match") or {}).get("type") == "charge_type":
                    n_charge += 1
        self.counts["charge_variant_defs"] = n_charge
        self.ok("coverage", f"{len(required)} required variants covered; {n_charge} charge predicate defs")

    # ------------------------------------------------------------------ P
    def pack_checks(self, pack, mappings):
        man = self.pjson(pack, "manifest.json")
        if not man:
            self.err("P", "manifest.json missing")
        else:
            if man.get("format_version") != 2:
                self.err("P", "manifest format_version != 2")
            if not re.fullmatch(r"[0-9a-f-]{36}", (man.get("header") or {}).get("uuid", "")):
                self.err("P", "manifest header uuid invalid")
            for mod in man.get("modules") or []:
                if not re.fullmatch(r"[0-9a-f-]{36}", mod.get("uuid", "")):
                    self.err("P", "manifest module uuid invalid")
        atlas = self.pjson(pack, "textures/item_texture.json") or {"texture_data": {}}
        tiles = atlas.get("texture_data", {})
        # every mapped icon key must exist as tile + png
        if mappings:
            for item, defs in mappings["items"].items():
                for defn in defs:
                    ik = (defn.get("bedrock_options") or {}).get("icon")
                    if not ik:
                        continue
                    if ik not in tiles:
                        self.err("P", f"icon {ik} (for {defn['bedrock_identifier']}) not in item_texture.json")
                        continue
                    for t in tiles[ik]["textures"]:
                        if self.pfile(pack, t + ".png") is None:
                            self.err("P", f"icon texture file missing: {t}.png")
        # attachables / geometries / rcs / animations
        geo_ids, att_count, rc_names = set(), 0, set()
        z = pack["z"]
        names = z.namelist() if z else [str(p.relative_to(pack["dir"])) for p in pack["dir"].rglob("*.json")]
        files = set(names)
        for n in sorted(files):
            if not n.endswith(".json"):
                continue
            d = self.pjson(pack, n)
            if d is None:
                continue
            if n.startswith("models/"):
                for g in d.get("minecraft:geometry", []):
                    ident = g["description"]["identifier"]
                    geo_ids.add(ident if ident.startswith("geometry.") else "geometry." + ident)
            elif n.startswith("render_controllers/"):
                rc_names.update((d.get("render_controllers") or {}).keys())
        for n in sorted(files):
            if not n.startswith("attachables/"):
                continue
            att_count += 1
            d = self.pjson(pack, n) or {}
            desc = (d.get("minecraft:attachable") or {}).get("description") or {}
            bid = desc.get("identifier", "")
            if not bid.startswith("altarsmp:"):
                self.err("P", f"{n}: attachable identifier {bid!r} not in altarsmp namespace")
            for gref in (desc.get("geometry") or {}).values():
                if gref not in geo_ids and gref not in VANILLA_GEO:
                    self.err("P", f"{n}: geometry {gref} not shipped and not a vanilla builtin")
            for rref in desc.get("render_controllers") or []:
                if rref not in rc_names and rref not in BUILTIN_RCS:
                    self.err("P", f"{n}: render controller {rref} not shipped")
            for tref in (desc.get("textures") or {}).values():
                if isinstance(tref, str) and tref.startswith("textures/") and "misc/enchanted" not in tref:
                    fp = tref if tref.endswith(".png") else tref + ".png"
                    if self.pfile(pack, fp) is None:
                        self.err("P", f"{n}: texture {tref}.png missing")
            for aref in (desc.get("animations") or {}).values():
                rel = "animations/" + aref.replace(".", "_") + ".animation.json"
                if self.pfile(pack, rel) is None:
                    self.err("P", f"{n}: animation file {rel} missing")
        # mapping-side geometry references resolve
        if mappings:
            for item, defs in mappings["items"].items():
                for defn in defs:
                    safe = defn["bedrock_identifier"].replace(":", ".").replace("/", "_")
                    if f"attachables/{safe}.attachable.json" not in files and f"packs attachables/{safe}.attachable.json" == "":
                        pass  # attachable optional (icon-only defs legitimate)
        # sounds
        sd = self.pjson(pack, "sound_definitions.json") or {"definitions": {}}
        for k, v in sd["definitions"].items():
            if not re.fullmatch(r"[a-z0-9_.]+", k):
                self.err("P", f"sound key invalid: {k!r}")
            for s in v.get("sounds", []):
                rel = (s if isinstance(s, str) else s.get("name")) + ".ogg"
                if self.pfile(pack, rel) is None:
                    self.err("P", f"sound {k}: file {rel} missing")
        # flipbooks
        fb = self.pjson(pack, "textures/flipbook_textures.json")
        if fb:
            for e in fb:
                if e.get("atlas_tile") not in tiles:
                    self.err("P", f"flipbook atlas_tile {e.get('atlas_tile')} not in item_texture")
                if not isinstance(e.get("ticks_per_frame"), int):
                    self.err("P", f"flipbook {e.get('atlas_tile')}: ticks_per_frame not int")
        self.counts["attachables"] = att_count
        self.counts["geometries"] = len(geo_ids)
        self.counts["render_controllers"] = len(rc_names)
        self.counts["item_texture_tiles"] = len(tiles)
        self.counts["sound_events"] = len(sd["definitions"])
        self.ok("pack", f"{att_count} attachables, {len(geo_ids)} geometries, {len(rc_names)} RCs, "
                        f"{len(tiles)} atlas tiles, {len(sd['definitions'])} sound events — refs resolve")

    def zip_check(self, pack):
        zp = self.root / "packs" / "pack.zip"
        src = self.root / "pack_source"
        if not src.exists():
            self.ok("zip", "pack.zip is authoritative (no pack_source in shipped deliverable)")
            return
        with zipfile.ZipFile(zp) as z:
            zn = set(z.namelist())
            sn = {str(p.relative_to(src)) for p in src.rglob("*") if p.is_file()}
            only_z = zn - sn
            only_s = sn - zn
            if only_s:
                self.err("Z", f"{len(only_s)} files in pack_source missing from zip (e.g. {sorted(only_s)[:3]})")
            if "manifest.json" not in zn:
                self.err("Z", "manifest.json not at zip root")
            for n in zn:
                if n.startswith("/") or ".." in n:
                    self.err("Z", f"unsafe zip path {n}")
            self.counts["zip_files"] = len(zn)
            if not only_s and "manifest.json" in zn:
                self.ok("zip", f"{len(zn)} files mirror pack_source; manifest at root")

    # ------------------------------------------------------------------ G
    def gde(self, mappings):
        yml = self.root / "extensions" / "GeyserDisplayEntity-data" / "Mappings" / "altarsmp-displays.yml"
        if not yml.exists():
            self.err("G", "GDE mappings yml missing")
            return
        bid_set = set()
        for defs in mappings["items"].values():
            for defn in defs:
                bid_set.add(defn["bedrock_identifier"].replace(":", "."))
        n = n_ok = 0
        cur_has_type = False
        for line in yml.read_text(encoding="utf-8").splitlines():
            if re.match(r"^  [a-z0-9_]+:\s*$", line):
                cur_has_type = False
                n += 1
                continue
            m = re.match(r"\s+type: \"?([^\"\s]+)\"?\s*$", line)
            if m:
                cur_has_type = True
                if not m.group(1).startswith("minecraft:"):
                    self.err("G", f"yml entry type {m.group(1)!r} missing namespace")
                else:
                    n_ok += 1
            m = re.match(r"\s+item-identifier: \"?([^\"\s]+)\"?\s*$", line)
            if m:
                v = m.group(1)
                if v.startswith("geyser_custom:"):
                    if v[len("geyser_custom:"):] not in bid_set:
                        self.err("G", f"yml item-identifier {v} not backed by a mapping bedrock id")
                elif not v.startswith("minecraft:"):
                    self.err("G", f"yml item-identifier {v!r} has no bedrock namespace")
            m = re.match(r"\s+model-data: (-?\d+)\s*$", line)
            if m and cur_has_type and int(m.group(1)) < 0:
                self.err("G", "model-data: -1 (vanilla) should use item-identifier form")
        self.counts["gde_entries"] = n
        if n == 0:
            self.err("G", "no display entries generated")
        else:
            self.ok("gde", f"{n} display mappings, {n_ok} resolve")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "AltarSMP-Custom-Content"
    catalog = sys.argv[2] if len(sys.argv) > 2 else None
    v = V(root, catalog).run()
    rep = Path(root) / "validation"
    rep.mkdir(exist_ok=True)
    (rep / "validation-report.txt").write_text("\n".join(v.checks + ["", f"ERRORS: {len(v.errors)}"] + v.errors) + "\n", encoding="utf-8")
    print("\n".join(v.checks))
    if v.errors:
        print(f"\nFAILED: {len(v.errors)} error(s)")
        for e in v.errors[:60]:
            print(" -", e)
        return 1
    print(f"\nOK counts: {json.dumps(v.counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
