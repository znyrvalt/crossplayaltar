"""
AltarSMP Fabric 2.0.5 -> Bedrock crossplay package generator.

Inputs (all from the five authoritative reference files, discovered programmatically):
  docs/catalog/custom-items.json   - every required (java item, CMD) variant + state trees
  <java rp root>                   - AltarSMP-ResourcePack.zip extraction (models/textures/sounds)
  <fab root>                       - altarsmp-fabric-2.0.5.jar extraction (assets + sounds)
  <fabsrc root>                    - sources (display usage map, playSound calls)

Emits into the deliverable dir:
  pack_source/**      complete Bedrock resource pack (textures, geometry, attachables,
                      animations, render controllers, sounds, lang, manifest, flipbooks)
  packs/pack.zip      zipped pack_source
  custom_mappings/geyser_item_mappings.json (+ block/skull/waypoint files, valid-empty)
  lang/*.lang         Geyser locale overrides (custom item display names)
  GeyserDisplayEntity template: config.yml + Mappings/altarsmp-displays.yml
  build-report.json   machine-readable per-variant detail for the validator

Conversion formulas (geometry/animation/attachable/RC) ported from GeyserMC Rainbow
(LGPL-3.0, (c) GeyserMC contributors).
"""

import json
import re
import shutil
import uuid as U
import zipfile
from pathlib import Path

from PIL import Image

from . import java_rp
from . import textures as T
from .bedrock_model import (GENERATED_DISPLAY, HANDHELD_DISPLAY,
                            VANILLA_GENERATED_ELEMENTS, build_attachable,
                            build_geometry, build_render_controller,
                            display_animations, is_generated_parent)

PACK_NS = "altarsmp"
ENGINE = [1, 21, 30]
PACK_UUID = str(U.uuid5(U.NAMESPACE_URL, "geysermc:altarsmp:resource:pack:v2"))
MODULE_UUID = str(U.uuid5(U.NAMESPACE_URL, "geysermc:altarsmp:resource:module:v2"))
ICON_DIR = "textures/items/altarsmp"

TAG_STRIP = re.compile(r"<[^>]+>|\{[^}]*\}|§[0-9a-fk-or]")


def bsafe(s):
    return s.replace(":", ".").replace("/", "_")


def slugify(item, cmd, suffix=""):
    base = item.split(":")[-1]
    return f"{base}_c{cmd}{suffix}"


def plain(s):
    return TAG_STRIP.sub("", s or "").strip() or None


class Builder:
    def __init__(self, rp_root, fab_root, fabsrc_root, out_root, catalog_doc, version="2.0.5"):
        self.rp_root = Path(rp_root)
        self.fab_root = Path(fab_root)
        self.fabsrc_root = Path(fabsrc_root)
        self.out = Path(out_root)
        self.pack = self.out / "pack_source"
        if self.pack.exists():
            shutil.rmtree(self.pack)
        self.rp = java_rp.JavaRP(rp_root)
        self.catalog = catalog_doc["items"]
        self.version = version
        self._mcache = {}
        self.geos, self.anims, self.attaches, self.rcs = {}, {}, {}, {}
        self.item_atlas = {}
        self.flip_tiles, self.flip_raw = [], []
        self.mappings_items = {}
        self.lang = {}
        self.gde_entries = []
        self.report = {}
        self.warnings = []
        self.used_models = set()
        self.copied_tex = {}          # tex_id -> pack rel
        self.stats = dict(models=0, textures=0, geometries=0, attachables=0,
                          animations=0, render_controllers=0, defs=0, icons=0,
                          flipbooks=0, sounds=0, warning_items=0)

    # ------------------------------------------------------------ models
    def resolved(self, model_id):
        if model_id in self._mcache:
            return self._mcache[model_id]
        m = self.rp.resolve_model(model_id)
        roots = [str(r) for r in m["roots"]]
        flatparent = is_generated_parent(m["roots"]) or any(
            r.split(":")[-1] in ("item/generated", "item/handheld") for r in roots)
        if flatparent and not m["elements"]:
            m["elements"] = VANILLA_GENERATED_ELEMENTS
            if "layer0" not in m["textures"] and m["textures"]:
                first = next(iter(m["textures"].values()))
                m["textures"]["layer0"] = first
            if not m.get("gui_light"):
                m["gui_light"] = "front"
        if any(r.split(":")[-1].endswith("handheld") for r in roots):
            for k, v in HANDHELD_DISPLAY.items():
                m["display"].setdefault(k, v)
        for k, v in GENERATED_DISPLAY.items():
            m["display"].setdefault(k, v)
        self._mcache[model_id] = m
        return m

    @staticmethod
    def model_is_flat(m):
        els = m.get("elements") or []
        if not els:
            return True
        for el in els:
            fr, to = el["from"], el["to"]
            axes = sum(1 for i in range(3) if abs(float(to[i]) - float(fr[i])) > 0.01)
            if axes >= 3:
                return False
        return True

    # ------------------------------------------------------------ textures
    def copy_tex(self, tex_id):
        tex_id = str(tex_id).lstrip("#")
        if tex_id in self.copied_tex:
            return self.copied_tex[tex_id]
        ns, _, path = tex_id.partition(":")
        if not path:
            ns, path = "minecraft", tex_id
        src = self.rp.texture_path(tex_id)
        if not src.exists():
            self.copied_tex[tex_id] = None
            return None
        out = f"{ICON_DIR}/{ns}/{path}"          # extensionless bedrock-style ref
        dst = self.pack / (out + ".png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        img = T.load_png(src)
        if img is None:
            self.copied_tex[tex_id] = None
            return None
        img.save(dst)
        rec = {"rel": out, "file": out + ".png", "size": img.size, "anim": T.mcmeta_animation(src)}
        self.copied_tex[tex_id] = rec
        self.stats["textures"] += 1
        return rec

    # ------------------------------------------------------------ icon
    def icon_from_model(self, m, name):
        # key by TEXTURE ID (faces reference resolved ids after deref), keep slots too
        slots = {}
        for slot, tid in (m.get("textures") or {}).items():
            rec = self.copy_tex(tid)
            if not rec:
                continue
            img = T.load_png(self.pack / rec["file"])
            if img:
                tsz = m.get("texture_size", 16)
                slots[slot] = (img, tsz)
                slots[str(tid).lstrip("#")] = (img, tsz)
        if not slots:
            return None
        if self.model_is_flat(m) and "layer0" in slots:
            layers = [slots[s][0] for s in ("layer0", "layer1") if s in slots]
            img = T.render_flat_icon(layers)
        else:
            # 3D model: icon = dominant texture (Rainbow convention; real artwork, no raster
            # fabrication). Bedrock hotbars show the flat tile; the 3D shape renders via the
            # attachable geometry in-hand/on-stands. Animated strips: crop first frame square.
            counts = {}
            for el in (m.get("elements") or []):
                for fd in (el.get("faces") or {}).values():
                    t = str(fd.get("texture", "")).lstrip("#")
                    if t in slots:
                        counts[t] = counts.get(t, 0) + 1
            primary = max(counts, key=counts.get) if counts else next(iter(slots))
            img = slots[primary][0].copy()
        # animated strip icons must be a single frame: crop top square
        if img.size[1] > img.size[0]:
            img = img.crop((0, 0, img.size[0], img.size[0]))
        rel = f"{ICON_DIR}/{name}.png"
        p = self.pack / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p)
        self.stats["icons"] += 1
        return rel

    # ------------------------------------------------------------ flipbooks
    def register_flipbook(self, tex_rec, atlas_tile):
        anim = tex_rec.get("anim")
        if not anim:
            return None
        w, h = tex_rec["size"]
        fr = anim.get("frametime", 1)
        if isinstance(fr, list):
            fr = fr[0]
        try:
            fr = max(1, int(fr))
        except Exception:
            fr = 1
        nframes = max(1, h // w) if w else 1
        entry = {"flipbook_texture": tex_rec["rel"], "atlas_tile": atlas_tile,
                 "ticks_per_frame": fr, "replicate": 0}
        self.flip_tiles.append(entry)
        self.flip_raw.append({"texture": tex_rec["rel"], "frame_time": fr,
                              "frame_height": w, "frame_width": w, "source_height": h,
                              "source_width": w, "atlas_flipbook": False})
        self.stats["flipbooks"] += 1
        return {"fps": round(20.0 / fr, 4), "frames": nframes}

    # ------------------------------------------------------------ definition
    def emit_def(self, java_item, cmd, slug_, idle_model, *, icon_model=None,
                 predicate=None, handheld=False, equippable=None, protection=None,
                 display_name=None, components=None, note="", emit_mapping=True):
        bid = f"{PACK_NS}:{slug_}"
        safe = bsafe(bid)
        gid = f"{PACK_NS}_{slug_}"
        entry = {"java_item": java_item, "cmd": cmd, "bedrock_identifier": bid,
                 "model": idle_model, "note": note}
        m = self.resolved(idle_model) if idle_model else None
        mm = self.resolved(icon_model) if icon_model else m

        tex_ids = []
        for src in (m, mm):
            if src:
                for tid in sorted({str(v).lstrip("#") for v in (src.get("textures") or {}).values()}):
                    if tid not in tex_ids:
                        tex_ids.append(tid)
        tex_recs = {}
        for tid in tex_ids:
            rec = self.copy_tex(tid)
            if rec:
                tex_recs[tid] = rec

        roots = [str(r) for r in (m.get("roots") if m else [])]
        clear_marker = m is not None and not m["elements"] and any(
            str(r).replace("minecraft:", "").rstrip(".json").endswith("block/clear") for r in roots)
        if clear_marker:
            # invisible marker model (heavy_core 999 etc.) -> zero-size cube geometry
            bid_ = bid
            gid_ = gid
            self.geos[gid_] = {
                "format_version": "1.21.0",
                "minecraft:geometry": [{"description": {
                    "identifier": f"geometry.{gid_}",
                    "texture_width": 16, "texture_height": 16,
                    "visible_bounds_width": 0, "visible_bounds_height": 0,
                    "visible_bounds_offset": [0, 0, 0]},
                    "bones": [{"name": "bone", "pivot": [0, 0, 0],
                              "cubes": [{"origin": [0, 0, 0], "size": [0, 0, 0],
                                         "uv": [0, 0, 0, 0]}]}]}]}
            self.stats["geometries"] += 1
            tex1x1 = f"{ICON_DIR}/clear1x1"
            (self.pack / (tex1x1 + ".png")).parent.mkdir(parents=True, exist_ok=True)
            T.transparent((1, 1)).save(self.pack / (tex1x1 + ".png"))
            self.attaches[bsafe(bid_)] = build_attachable(bid_, gid_, {"default": tex1x1})
            self.stats["attachables"] += 1
            rcn, rc = build_render_controller(bid_, ["default"])
            self.rcs[bsafe(bid_)] = rc
            self.stats["render_controllers"] += 1
            self._clear_icon = tex1x1
        mapping_icon = None
        if not tex_recs:
            entry["no_textures"] = True
            if clear_marker:
                self.item_atlas[safe] = {"textures": [self._clear_icon]}
                mapping_icon = safe
            self.warnings.append(f"{java_item}|{cmd}::{slug_}: model {idle_model} has no textures available in the pack (icon falls back to base-item look)")
        else:
            flat = bool(m and self.model_is_flat(m))
            # ---- icon from the GUI-state model (or idle)
            icon_src = mm or m
            icon_rel = self.icon_from_model(icon_src, safe) if icon_src else None
            if icon_rel:
                self.item_atlas[safe] = {"textures": [icon_rel[:-4] if icon_rel.endswith(".png") else icon_rel]}
                mapping_icon = safe
            # ---- geometry + attachable
            if m and m["elements"] and not flat:
                ids = sorted(tex_recs.keys())
                stitched = len(ids) > 1
                if stitched:
                    imgs = [(t, Image.open(self.pack / tex_recs[t]["file"]).convert("RGBA")) for t in ids]
                    canvas, offs = T.stitch(imgs)
                    rel = f"{ICON_DIR}/{slug_}_atlas.png"
                    (self.pack / rel).parent.mkdir(parents=True, exist_ok=True)
                    canvas.save(self.pack / rel)
                    tex_rel = rel
                    W, H = canvas.size
                else:
                    tex_rel = tex_recs[ids[0]]["rel"]
                    W, H = Image.open(self.pack / tex_recs[ids[0]]["file"]).size
                    offs = {}
                tsz = m.get("texture_size", 16) or 16
                uvmap = {}
                for slot, tid in (m.get("textures") or {}).items():
                    tid = str(tid).lstrip("#")
                    if tid not in tex_recs:
                        continue
                    w0, h0 = tex_recs[tid]["size"]
                    ox = offs.get(tid, (0, 0, 0, 0))[0]
                    uvmap[tid] = (w0 / tsz, h0 / tsz, float(ox), 0.0)
                self.geos[gid] = build_geometry(gid, m, uvmap, W, H)
                self.stats["geometries"] += 1
                self.used_models.add(idle_model)
                anims = display_animations(gid, m.get("display") or {}) or {}
                anim_ids = {}
                for name, body in anims.items():
                    self.anims[name] = body
                    self.stats["animations"] += 1
                    key = {"hold_first_person": "first_person", "hold_third_person": "third_person",
                           "head": "on_head", "fixed": "on_display", "ground": "on_display"}.get(name.split(".")[-1])
                    if key:
                        anim_ids.setdefault(key, name)
                att = build_attachable(bid, gid, {"default": tex_rel[:-4] if tex_rel.endswith(".png") else tex_rel},
                                       animation=anim_ids or None)
                # animated texture on 3D geo: attachable texture flip (uv_animation-style)
                if not stitched and len(ids) == 1:
                    fb = self.register_flipbook(tex_recs[ids[0]], safe)
                    if fb:
                        desc = att["minecraft:attachable"]["description"]
                        desc["texture_animations"] = {"default": {
                            "size": [Image.open(self.pack / tex_recs[ids[0]]["file"]).size[0],
                                     Image.open(self.pack / tex_recs[ids[0]]["file"]).size[0]],
                            "fps": fb["fps"]}}
                self.attaches[safe] = att
                self.stats["attachables"] += 1
                rcn, rc = build_render_controller(bid, ["default"])
                self.rcs[safe] = rc
                self.stats["render_controllers"] += 1
            elif m:
                # flat sprite item: geometry.item_sprite builtin + render controller builtin
                ids = sorted(tex_recs.keys())
                slot = "layer0" if "layer0" in (m.get("textures") or {}) else next(iter(m.get("textures") or {"0": None}))
                src_tid = str(m["textures"].get(slot) or (next(iter(ids)) if ids else "")).lstrip("#")
                base_rec = tex_recs.get(src_tid)
                tex_rel = base_rec["rel"] if base_rec else tex_recs[ids[0]]["rel"]
                fb = self.register_flipbook(tex_recs[ids[0]] if base_rec is None else base_rec, safe)
                desc = {
                    "identifier": bid,
                    "materials": {"default": "entity_alphatest", "enchanted": "entity_alphatest_glint"},
                    "textures": {"default": tex_rel[:-4] if tex_rel.endswith(".png") else tex_rel, "enchanted": "textures/misc/enchanted_item_glint"},
                    "geometry": {"default": "geometry.item_sprite"},
                    "render_controllers": ["controller.render.item_sprite"],
                }
                if fb:
                    desc["texture_animations"] = {"default": {
                        "size": [tex_recs[ids[0]]["size"][0]] * 2, "fps": fb["fps"]}}
                self.attaches[safe] = {"format_version": "1.21.30",
                                       "minecraft:attachable": {"description": desc}}
                self.stats["attachables"] += 1
                self.used_models.add(idle_model)

        if not emit_mapping:
            entry["no_mapping"] = "java item does not exist vanilla-side; assets kept for completeness"
            self.report[f"{java_item}|{cmd}::{slug_}"] = entry
            return entry
        d = {"type": "legacy", "custom_model_data": cmd, "bedrock_identifier": bid}
        opts = {}
        if mapping_icon:
            opts["icon"] = mapping_icon
        if handheld:
            opts["display_handheld"] = True
        if protection:
            opts["protection_value"] = int(protection)
        if opts:
            d["bedrock_options"] = opts
        if display_name:
            d["display_name"] = display_name
            self.lang[f"item.{safe}"] = display_name
        comp = dict(components or {})
        if equippable:
            comp["minecraft:equippable"] = equippable
        if comp:
            d["components"] = comp
        if predicate:
            d["predicate"] = predicate
        self.mappings_items.setdefault(java_item, []).append(d)
        self.stats["defs"] += 1
        self.report[f"{java_item}|{cmd}::{slug_}"] = entry
        return entry

    # ------------------------------------------------------------ armor layers
    def emit_armor_layers(self, armorj, armor_defs_by_base):
        humanoid = self.rp_root / "assets/custom/textures/entity/equipment/humanoid/copper.png"
        legs = self.rp_root / "assets/custom/textures/entity/equipment/humanoid_leggings/copper.png"
        eq = {}
        for label, f in (("copper_layer_1", humanoid), ("copper_layer_2", legs)):
            if f.exists():
                img = T.load_png(f)
                rel = f"textures/models/armor/{label}.png"
                (self.pack / rel).parent.mkdir(parents=True, exist_ok=True)
                img.save(self.pack / rel)
                eq[label] = rel[:-4] if rel.endswith(".png") else rel
        if not eq:
            self.warnings.append("copper equipment textures missing in pack; armor layers skipped")
            return
        geo_for = {"helmet": ("geometry.player.armor.helmet", "helmet"),
                   "chestplate": ("geometry.player.armor.chest", "chestplate"),
                   "leggings": ("geometry.player.armor.legs", "leggings"),
                   "boots": ("geometry.player.armor.boots", "boots")}
        self.armor_emitted = []
        for base, (bid, slug) in armor_defs_by_base.items():
            which = next((w for w in geo_for if base.endswith(w)), None)
            if not which:
                continue
            geo, var = geo_for[which]
            safe = bsafe(bid)
            layer = "copper_layer_2" if which == "leggings" else "copper_layer_1"
            tex = eq.get(layer, eq["copper_layer_1"])
            rcn = f"controller.render.armor.{safe}"
            self.rcs[safe + "_armor"] = {"format_version": "1.10.0", "render_controllers": {rcn: {
                "part_visibility": [{"*": f"variable.{var}_layer_visible > 0.0"}],
                "geometry": "Geometry.default",
                "materials": [{"*": "Material.default"}],
                "textures": ["Texture.default"],
            }}}
            slot_q = {"helmet": "minecraft:head_slot", "chestplate": "minecraft:chest_slot",
                      "leggings": "minecraft:legs_slot", "boots": "minecraft:feet_slot"}[which]
            pre = [
                f"variable.{var}_layer_visible = 1.0;",
                f"variable.{var}_layer_visible = query.any_armor_equipped('{slot_q}') ? 0.0 : 1.0;",
            ]
            self.attaches[safe] = {"format_version": "1.21.30", "minecraft:attachable": {"description": {
                "identifier": bid,
                "materials": {"default": "armor", "enchanted": "armor_glint"},
                "textures": {"default": tex},
                "geometry": {"default": geo},
                "render_controllers": [rcn],
                "scripts": {"parent": "setup_armor", "pre_animation": pre},
            }}}


    # ------------------------------------------------------------ sounds
    def emit_sounds(self):
        defs = {}
        events = {}
        roots = [self.rp_root / "assets", self.fab_root / "assets"]
        for root in roots:
            if not root.exists():
                continue
            for sj in root.rglob("sounds.json"):
                try:
                    d = json.load(open(sj, encoding="utf-8"))
                except Exception:
                    continue
                ns = sj.parts[-2]
                for ev, spec in d.items():
                    if isinstance(spec, dict):
                        events.setdefault((ns, ev), (spec, sj))
        copied = []
        for (ns, ev), (spec, sj) in sorted(events.items()):
            sounds_out = []
            for item in spec.get("sounds", []):
                if isinstance(item, str):
                    item = {"name": item}
                nm = str(item.get("name", ""))
                if not nm:
                    continue
                if ":" in nm:
                    ns2, _, p2 = nm.partition(":")
                else:
                    ns2, p2 = ns, nm
                src = self.rp_root / "assets" / ns2 / "sounds" / (p2 + ".ogg")
                if not src.exists():
                    src = self.fab_root / "assets" / ns2 / "sounds" / (p2 + ".ogg")
                if not src.exists():
                    # nested event reference
                    if (ns2, p2) in events and (ns2, p2) != (ns, ev):
                        spec2, sj2 = events[(ns2, p2)]
                        continue
                    continue
                dst_rel = f"sounds/{ns2}/{p2}.ogg"
                dst = self.pack / dst_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copyfile(src, dst)
                    copied.append(dst_rel)
                e = {"name": dst_rel[:-4]}
                for k in ("volume", "pitch", "weight"):
                    if k in item:
                        e[k] = item[k]
                sounds_out.append(e)
            if not sounds_out:
                self.warnings.append(f"sound event {ns}:{ev} has no ogg in either reference pack (silent on both sides)")
                continue
            # Geyser maps java sound id "ns:path" -> bedrock "ns.path"; the event name itself
            # already carries dots (custom.nuke_incoming), so register both spellings.
            keys = {ev if ev.startswith(f"{ns}.") else f"{ns}.{ev}"}
            if ns == "minecraft":
                keys.add(ev)          # "custom.nuke_incoming" (bare form Geyser strips to)
            for k in sorted(keys):
                if re.fullmatch(r"[a-z0-9_.]+", k):
                    defs[k] = {"category": (spec.get("category", "neutral") or "neutral").lower(),
                               "sounds": sounds_out, "min_distance": 1.0}
        if defs:
            json.dump({"format_version": "1.14.0", "definitions": defs},
                      open(self.pack / "sound_definitions.json", "w"), indent=1)
        self.stats["sounds"] = len(copied)
        self.sound_keys = sorted(defs.keys())
        self.sound_files = sorted(copied)

    # ------------------------------------------------------------ outputs
    def write_pack(self):
        p = self.pack
        (p / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
        json.dump({
            "format_version": 2,
            "header": {"name": "AltarSMP Custom Content (Bedrock)",
                       "description": f"AltarSMP {self.version} custom items, models, sounds, armor - generated for Geyser from the original Java resource pack. Do not edit.",
                       "uuid": PACK_UUID, "version": [2, 0, 5, 0],
                       "min_engine_version": ENGINE},
            "modules": [{"type": "resources", "uuid": MODULE_UUID, "version": [2, 0, 5, 0]}],
        }, open(p / "manifest.json", "w"), indent=1)

        def dump(sub, obj):
            f = p / sub
            f.parent.mkdir(parents=True, exist_ok=True)
            json.dump(obj, open(f, "w"), indent=1)

        for gid, geo in self.geos.items():
            dump(f"models/{gid}.geo.json", geo)
        for name, body in self.anims.items():
            safe_name = name.replace(".", "_")
            dump(f"animations/{safe_name}.animation.json",
                 {"format_version": "1.8.0", "animations": {name: body}})
        for safe, att in self.attaches.items():
            dump(f"attachables/{safe}.attachable.json", att)
        for safe, rc in self.rcs.items():
            dump(f"render_controllers/{safe}.controller.json", rc)
        if self.item_atlas:
            dump("textures/item_texture.json", {"resource_pack_name": "altarsmp",
                                                "texture_name": "atlas.items",
                                                "texture_data": self.item_atlas})
        if self.flip_tiles:
            dump("textures/flipbook_textures.json", self.flip_tiles)
        texts = p / "texts"
        texts.mkdir(exist_ok=True)
        (texts / "en_US.lang").write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(self.lang.items())) + "\n", encoding="utf-8")
        (texts / "languages.json").write_text(json.dumps(["en_US"]), encoding="utf-8")

    def write_mappings(self, out_custom):
        out = Path(out_custom)
        out.mkdir(parents=True, exist_ok=True)
        json.dump({"format_version": 2, "items": self.mappings_items},
                  open(out / "geyser_item_mappings.json", "w"), indent=2)
        for name, key in (("geyser_block_mappings.json", "blocks"),
                          ("geyser_skull_mappings.json", "skulls"),
                          ("geyser_waypoint_style_mappings.json", "waypoint_styles")):
            json.dump({"format_version": 2, key: {}}, open(out / name, "w"), indent=2)

    def write_lang(self, out_lang):
        d = Path(out_lang)
        d.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"{k}={v}" for k, v in sorted(self.lang.items())) + "\n"
        (d / "en_US.lang").write_text(body, encoding="utf-8")

    def finalize(self, out_report):
        json.dump({"stats": self.stats, "warnings": self.warnings,
                   "report": self.report, "sound_keys": getattr(self, "sound_keys", []),
                   "sound_files": getattr(self, "sound_files", [])},
                  open(Path(out_report), "w"), indent=1)
