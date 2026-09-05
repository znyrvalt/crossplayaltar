"""
Reader for the ORIGINAL Java resource pack (AltarSMP-ResourcePack.zip contents).

Resolves:
  * item model DEFINITION files (1.21.4+ `assets/<ns>/items/*.json`), including the
    dispatch graph (range_dispatch / condition / select / composite / special),
  * model JSONs (elements, textures, parents, display transforms, gui_light, ...),
  * texture existence checks and sizes (PNG header peek, no pixel decode).

Everything here is pure parsing; no assumptions about which items exist.
"""

import json
import os
import re
import struct
from pathlib import Path


def png_size(path):
    """Return (w, h) of a PNG by reading the IHDR chunk (no Pillow needed)."""
    try:
        with open(path, "rb") as f:
            head = f.read(33)
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return w, h
    except OSError:
        pass
    return None


class JavaRP:
    def __init__(self, root):
        self.root = Path(root)

    # ------------------------------------------------------------ files
    def model_path(self, loc):
        """assets/<ns>/models/<path>.json for a ResourceLocation string."""
        ns, _, p = str(loc).partition(":")
        if not p:
            ns, p = "minecraft", loc
        return self.root / "assets" / ns / "models" / (p + ".json")

    def texture_path(self, loc):
        ns, _, p = str(loc).partition(":")
        if not p:
            ns, p = "minecraft", loc
        return self.root / "assets" / ns / "textures" / (p + ".png")

    def definition_path(self, loc):
        ns, _, p = str(loc).partition(":")
        if not p:
            ns, p = "minecraft", loc
        return self.root / "assets" / ns / "items" / (p + ".json")

    def item_definition_id(self, java_item):
        """The implicit item model definition id for a vanilla java item id."""
        return java_item

    # ------------------------------------------------------------ json
    _cache = {}

    def load_json(self, path):
        key = str(path)
        if key in self._cache:
            return self._cache[key]
        val = None
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    val = json.load(f)
            except json.JSONDecodeError as e:
                val = {"__error__": str(e), "__path__": key}
        self._cache[key] = val
        return val

    # ------------------------------------------------------------ models
    def resolve_model(self, loc, _seen=None):
        """
        Merge parent chain -> {textures, elements, display, gui_light, ambientocclusion,
        texture_size, overhead/ground overrides...} returns dict with
          'textures': slot -> texture id ('#x' entries already resolved),
          'elements': list of raw element dicts,
          'display': merged display transforms,
          'missing': list of unresolvable references.
        """
        _seen = _seen or []
        result = {"textures": {}, "elements": [], "display": {}, "gui_light": None,
                  "texture_size": 16, "roots": [], "missing": []}
        stack = [str(loc)]
        order = []
        cur = str(loc)
        # walk parents (child first list; merge later from root down)
        depth = 0
        while cur and depth < 24:
            depth += 1
            if cur in _seen:
                result["missing"].append(f"parent cycle at {cur}")
                break
            _seen.append(cur)
            p = self.model_path(cur)
            data = self.load_json(p)
            if data is None:
                result["missing"].append(f"model {cur} not found")
                break
            if "__error__" in data:
                result["missing"].append(f"model {cur} invalid json: {data['__error__']}")
                break
            order.append((cur, data))
            cur = data.get("parent")
        for ident, data in reversed(order):
            result["roots"].append(ident)
            ts = data.get("texture_size", result["texture_size"])
            if isinstance(ts, (list, tuple)):
                result["texture_size"] = max(int(v) for v in ts)
            else:
                try:
                    result["texture_size"] = int(ts)
                except (TypeError, ValueError):
                    pass
            if data.get("gui_light") is not None:
                result["gui_light"] = data["gui_light"]
            if "display" in data:
                result["display"].update(data["display"])
            textures = data.get("textures", {}) or {}
            resolved = {}
            for slot, ref in textures.items():
                if isinstance(ref, str) and ref.startswith("#"):
                    target = ref[1:]
                    ref = result["textures"].get(target) or (textures.get(target))
                    if isinstance(ref, str) and ref.startswith("#"):
                        ref = None
                if isinstance(ref, str):
                    resolved[slot] = ref
            result["textures"].update({k: v for k, v in resolved.items() if v})
            for el in data.get("elements", []) or []:
                result["elements"].append(el)
        # resolve remaining '#' references against own texture table
        def deref(ref):
            seen = 0
            while isinstance(ref, str) and ref.startswith("#") and seen < 8:
                ref = result["textures"].get(ref[1:])
                seen += 1
            return ref
        result["textures"] = {k: deref(v) for k, v in result["textures"].items()
                              if isinstance(v, str) and not v.startswith("#")}
        # rewrite element face '#slot' references to concrete texture ids (merged-table
        # semantics, exactly like vanilla's lazy resolve) so downstream consumers agree
        for el in result["elements"]:
            for fdef in (el.get("faces") or {}).values():
                t = fdef.get("texture")
                if isinstance(t, str) and t.startswith("#"):
                    d = deref(t)
                    if d:
                        fdef["texture"] = d
        return result

    # ------------------------------------------------------------ item definitions
    def definition_for(self, java_item_id):
        data = self.load_json(self.definition_path(java_item_id))
        return data

    def iter_definitions(self):
        for ns in sorted(os.listdir(self.root / "assets")):
            items_dir = self.root / "assets" / ns / "items"
            if not items_dir.is_dir():
                continue
            for fn in sorted(os.listdir(items_dir)):
                if fn.endswith(".json"):
                    yield ns, fn[:-5]


# ---------------------------------------------------------------- dispatch walker
class DispatchWalker:
    """
    Walks the 1.21.4 item definition tree and answers, for a concrete stack state,
    which model the java client would pick. Emits 'variants' = sets of leaf models
    with the state properties that select them.
    """

    def __init__(self, rp: JavaRP):
        self.rp = rp

    def model_of(self, node):
        """Simple case: definition node is {'type':'minecraft:model','model': 'x'}"""
        if isinstance(node, dict) and DispatchWalker._t(node) == "model":
            if "model" in node:
                return node["model"]
        return None

    def range_entry_for(self, node, prop, value):
        """Java range_dispatch semantics: greatest threshold <= value, else fallback."""
        entries = [e for e in node.get("entries", []) if isinstance(e, dict)]
        best = None
        for e in entries:
            thr = e.get("threshold")
            try:
                thr = float(thr)
            except (TypeError, ValueError):
                continue
            if value >= thr and (best is None or thr > best[0]):
                best = (thr, e["model"])
        return best[1] if best else node.get("fallback")

    def resolve_model_for_state(self, defn_root, *, cmd=None, using=False, display_context=None,
                                charge_type=None, pull=None):
        """
        Follow the dispatch tree for a concrete state; return final leaf model id or None.
        - cmd: first float of custom_model_data
        - using: player is using item
        - display_context: 'gui'|'ground'|'fixed'|'hand'|'head'...
        - charge_type: 'arrow'|'rocket' (crossbow)
        - pull: crossbow pull 0..1 / bow use_duration (already scaled per def)
        """
        node = defn_root.get("model", defn_root) if isinstance(defn_root, dict) else defn_root
        for _ in range(32):
            if not isinstance(node, dict):
                return None
            t = self._t(node)
            if t == "model":
                return node.get("model")
            prop = node.get("property", "")
            if t == "range_dispatch":
                prop = prop or ""
                if "custom_model_data" in prop:
                    if cmd is None:
                        node = node.get("fallback")
                        continue
                    node = self.range_entry_for(node, prop, float(cmd))
                    continue
                if "use_duration" in prop or "pull" in prop:
                    val = None
                    if pull is not None:
                        val = float(pull) * float(node.get("scale", 1.0) or 1.0)
                    if val is None:
                        node = node.get("fallback")
                        continue
                    node = self.range_entry_for(node, prop, val)
                    continue
                if "damage" in prop:
                    node = self.range_entry_for(node, prop, 1.0)
                    continue
                node = node.get("fallback")
                continue
            if t == "condition":
                cp = node.get("property", "")
                if cp.endswith("using_item"):
                    node = node.get("on_true") if using else node.get("on_false")
                    continue
                if cp.endswith("custom_model_data"):
                    idx = int(node.get("index", 0))
                    on = bool(node.get("on_true")) if node.get("on_true") is True else node.get("on_true")
                    off = node.get("on_false")
                    # flags: mod sets floats only -> treat flag presence as unknown (False)
                    node = off if (cmd is None) else off
                    continue
                if cp.endswith("broken") or cp.endswith("damaged"):
                    node = node.get("on_false")
                    continue
                if cp.endswith("fishing_rod_cast"):
                    node = node.get("on_false")
                    continue
                node = node.get("on_false")
                continue
            if t == "select":
                sp = node.get("property", "")
                cases = node.get("cases", [])
                want = None
                if sp.endswith("display_context"):
                    want = display_context
                elif sp.endswith("charge_type"):
                    want = charge_type
                elif sp.endswith("context_dimension"):
                    want = None
                if want is not None:
                    hit = None
                    for c in cases:
                        when = c.get("when")
                        if when is None:
                            continue
                        wl = when if isinstance(when, list) else [when]
                        if want in wl:
                            hit = c["model"]
                            break
                    node = hit if hit is not None else node.get("fallback")
                    continue
                node = node.get("fallback")
                continue
            if t == "composite":
                # pick the first plain-model child for static resolution
                for sub in node.get("model", []) or []:
                    m = self.resolve_model_for_state({"model": sub}, cmd=cmd, using=using,
                                                     display_context=display_context,
                                                     charge_type=charge_type, pull=pull)
                    if m:
                        return m
                return None
            if t == "special":
                return None
            return None
        return None

    @staticmethod
    def _t(node):
        t = (node.get("type") or "model")
        return t.split(":")[-1]

    def all_cmd_variants(self, defn_root):
        """
        Enumerate every CMD dispatch branch of the root range_dispatch keyed to
        custom_model_data (this is the mod's only mechanism). Returns:
          {cmd_int: {"idle": model-or-tree, ...resolved states}}
        by walking thresholds; each branch is then expanded for using/charge states.
        """
        out = {}
        node = defn_root.get("model", defn_root)
        if not (isinstance(node, dict) and self._t(node) == "range_dispatch"
                and "custom_model_data" in node.get("property", "")):
            return out
        for e in node.get("entries", []):
            thr = e.get("threshold")
            if thr is None:
                continue
            out[int(thr)] = e["model"]
        return out

    def states_of_branch(self, branch):
        """
        Expand one dispatch branch into named states:
          idle / using / gui / ground / fixed / loaded_arrow / loaded_rocket / pull0..n
        Returns list of (state_name, model_id).
        """
        states = []

        def walk(node, prefix):
            if not isinstance(node, dict):
                return
            t = DispatchWalker._t(node)
            if t == "model":
                states.append((prefix, node.get("model")))
                return
            prop = node.get("property", "")
            if t == "condition" and prop.endswith("using_item"):
                walk(node.get("on_true"), prefix + ".using")
                walk(node.get("on_false"), prefix)
                return
            if t == "select" and prop.endswith("display_context"):
                for c in node.get("cases", []):
                    when = c.get("when")
                    wl = when if isinstance(when, list) else [when]
                    for w in wl:
                        walk(c["model"], prefix + f".ctx_{w}")
                walk(node.get("fallback"), prefix)
                return
            if t == "select" and prop.endswith("charge_type"):
                for c in node.get("cases", []):
                    when = c.get("when")
                    wl = when if isinstance(when, list) else [when]
                    for w in wl:
                        walk(c["model"], prefix + f".charge_{w}")
                walk(node.get("fallback"), prefix)
                return
            if t == "range_dispatch" and ("pull" in prop or "use_duration" in prop):
                for i, e in enumerate(node.get("entries", []) or []):
                    walk(e["model"], prefix + f".pull{i+1}")
                walk(node.get("fallback"), prefix)
                return
            if t == "condition":
                # unsupported boolean condition: resolve false branch, record true as variant
                walk(node.get("on_false"), prefix)
                if node.get("on_true") is not None:
                    states.append((prefix + ".unsupported_" + prop.split(":")[-1], None))
                return
            walk(node.get("fallback"), prefix)
            return
        walk(branch, "idle")
        return states
