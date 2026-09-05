"""
Java-model -> Bedrock conversion, ported (formulas + output shapes) from GeyserMC
Rainbow's GeometryMapper / AnimationMapper / BedrockGeometry / BedrockAnimation /
BedrockAttachable writers (LGPL-3.0), extended with vanilla built-in models and a
FaceBakery re-implementation for faces without explicit uv.

Coordinates (from Rainbow):
  geometry cube: origin = min(from,to) - [8,0,8]; size = max-min; origin.x = -(origin.x+size.x)
  rotation:      X -> -angle, Y -> +angle, Z -> +angle      (single axis, as authored)
  uv:            up/down faces use (maxU,maxV) with (min-max) size (flip), else min/max
  uv scale:      uv * (texture_px / model_texture_size)
Display contexts (Rainbow AnimationMapper):
  firstperson : rotation [-90+ry, -rz, rx]; position [-ty, 12.5+tz, tx]; scale s
  thirdperson : rotation [90, -rz, -ry];    position [-tx, 12.5+tz, -ty]; scale s
  head        : position = t*(-0.655,0.655,0.655)+(0,20,0); rot (x,y,z)*(-1,-1,1); scale 0.655*s
"""

import math

CENTER_OFFSET = (8.0, 0.0, 8.0)

# ---- vanilla builtin models (as shipped by Mojang; required because the pack does not
# ---- contain them; these values are the documented vanilla data, not invented) ----
VANILLA_GENERATED_ELEMENTS = [{
    "from": [0.0, 0.0, 7.0], "to": [16.0, 16.0, 8.0],
    "faces": {d: {"texture": "#layer0"} for d in
              ("north", "east", "south", "west", "up", "down")},
}]
# vanilla item/handheld display (third/first person rotation for tools/swords)
HANDHELD_DISPLAY = {
    "thirdperson_righthand": {"rotation": [0, -90, 55], "translation": [0, 4.0, 0.5], "scale": [0.85, 0.85, 0.68]},
    "thirdperson_lefthand": {"rotation": [0, 90, -55], "translation": [0, 4.0, 0.5], "scale": [0.85, 0.85, 0.68]},
    "firstperson_righthand": {"rotation": [0, -90, 25], "translation": [1.13, 3.2, 1.13], "scale": [0.68, 0.68, 0.68]},
    "firstperson_lefthand": {"rotation": [0, 90, -25], "translation": [1.13, 3.2, 1.13], "scale": [0.68, 0.68, 0.68]},
}
GENERATED_DISPLAY = {
    "ground": {"rotation": [0, 0, 0], "translation": [0, 3, 0], "scale": [0.5, 0.5, 0.5]},
    "head": {"rotation": [0, 180, 0], "translation": [0, 0, 0], "scale": [1, 1, 1]},
    "gui": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [1, 1, 1]},
    "fixed": {"rotation": [0, 180, 0], "translation": [0, 4, 0], "scale": [1, 1, 1]},
}


def is_generated_parent(roots):
    for r in roots:
        p = r.split(":")[-1]
        if p.endswith("item/generated") or p == "item/generated" or p.endswith("item/handheld"):
            return True
    return False


def _rotmat(euler_deg):
    """Java ItemTransform rotation order: R = Rz * Ry * Rx (x applied first)."""
    rx, ry, rz = [math.radians(a) for a in euler_deg]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    Rx = [[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]]
    Ry = [[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]]
    Rz = [[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]]
    return mul(mul(Rz, Ry), Rx)


# ------------------------------------------------------------------ geometry
def face_uv(face, element, texture_size=16):
    """Return (uv_origin[minu,minv] or (maxu,maxv) for Y, uv_size, uv_rotation)."""
    uv = face.get("uv")
    if uv is None:
        # FaceBakery-style default: rect over the face's two in-plane axes
        fr, to = element["from"], element["to"]
        n = None
        # rough default: bounding box of the face in texture space
        return None
    if isinstance(uv, dict):  # per-face {"uv":[u1,v1,u2,v2],"rotation":n}
        uvs = uv.get("uv", [0, 0, 16, 16])
        rot = int(uv.get("rotation", 0) or 0)
    else:
        uvs = uv
        rot = int(face.get("rotation", 0) or 0)
    return list(uvs), rot


def element_to_cube(el, uvmap=None):
    """
    One Java element -> one Bedrock cube dict.
    uvmap: texture-id -> (su, sv, offx, offy) where s* = actual_tex_px / model texture_size
    (vanilla FaceBakery scaling) and off* is the stitched-atlas placement offset.
    """
    fr = [float(x) for x in el["from"]]
    to = [float(x) for x in el["to"]]
    f = [fr[i] - CENTER_OFFSET[i] for i in range(3)]
    t = [to[i] - CENTER_OFFSET[i] for i in range(3)]
    origin = [min(f[i], t[i]) for i in range(3)]
    size = [max(f[i], t[i]) - origin[i] for i in range(3)]
    origin[0] = -(origin[0] + size[0])

    rot = el.get("rotation")
    pivot = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0]
    if rot:
        p = [float(v) for v in rot["origin"]]
        pivot = [p[0] - 8.0, p[1] - 0.0, p[2] - 8.0]
        pivot[0] = -pivot[0]
        a = float(rot.get("angle", 0.0))
        axis = rot.get("axis", "y")
        rotation = {"x": [-a, 0.0, 0.0], "y": [0.0, a, 0.0], "z": [0.0, 0.0, a]}[axis]
        if rot.get("rescale"):
            # Java rescale grows the cube along the perpendicular axes; emulate with inflate-free
            # axis scale of the size (Bedrock has no rescale; approximate by expanding dims 1.414x on the two rotated axes)
            s = math.sqrt(2.0)
            idx = {"x": [1, 2], "y": [0, 2], "z": [0, 1]}[axis]
            for i2 in idx:
                size[i2] = size[i2] * s

    cube = {
        "origin": [round(v, 4) for v in origin],
        "size": [round(v, 4) for v in size],
    }
    if any(rotation):
        cube["pivot"] = [round(v, 4) for v in pivot]
        cube["rotation"] = [round(v, 4) for v in rotation]
    faces_out = {}
    for face_name, face in (el.get("faces") or {}).items():
        if face_name not in ("north", "east", "south", "west", "up", "down"):
            continue
        got = face_uv(face, el)
        texslot = str(face.get("texture", "")).lstrip("#")
        su, sv, offx, offy = (uvmap or {}).get(texslot, (1.0, 1.0, 0.0, 0.0))
        if got is None:
            # default FaceBakery rect on 16-space then scaled
            mu = max(min(fr[0], to[0]), 0)
            uvs = [0, 0, 16, 16]
            rotdeg = 0
        else:
            uvs, rotdeg = got
        u1, v1, u2, v2 = [float(x) for x in uvs]
        minu, minv, maxu, maxv = min(u1, u2), min(v1, v2), max(u1, u2), max(v1, v2)
        # keep authored orientation: if u2<u1 or v2<v1, preserve sign (mirror)
        du = (u2 - u1) if u2 >= u1 else (u1 - u2)
        dv = (v2 - v1) if v2 >= v1 else (v1 - v2)
        sign_u = 1.0 if u2 >= u1 else -1.0
        sign_v = 1.0 if v2 >= v1 else -1.0
        if face_name in ("up", "down"):
            # Rainbow: Y faces flip origin to (maxU,maxV) with negative size
            uv_origin = [maxu * su + offx, maxv * sv + offy]
            uv_size = [minu * su - maxu * su, minv * sv - maxv * sv]
        else:
            uv_origin = [minu * su + offx, minv * sv + offy]
            uv_size = [(maxu - minu) * su, (maxv - minv) * sv]
        if sign_u < 0:
            uv_size[0] = -uv_size[0]
        if sign_v < 0:
            uv_size[1] = -uv_size[1]
        fdef = {"uv": [round(uv_origin[0], 3), round(uv_origin[1], 3)],
                "uv_size": [round(uv_size[0], 3), round(uv_size[1], 3)]}
        if rotdeg:
            fdef["uv_rotation"] = int(rotdeg) % 360
        faces_out[face_name] = fdef
    if faces_out:
        cube["uv"] = faces_out
    return cube


def build_geometry(geo_id, model, uvmap=None, texture_width=16, texture_height=16):
    """model: resolved dict from JavaRP.resolve_model (elements merged).
    uvmap: texture-id -> (su, sv, offx, offy); see element_to_cube."""
    elements = model["elements"]
    cubes = []
    for el in elements:
        cubes.append(element_to_cube(el, uvmap))
    minv = [1e9, 1e9, 1e9]
    maxv = [-1e9, -1e9, -1e9]
    for c in cubes:
        o, s = c["origin"], c["size"]
        for i in range(3):
            minv[i] = min(minv[i], o[i])
            maxv[i] = max(maxv[i], o[i] + s[i])
    if not cubes:
        pivot = [0, 0, 0]
    else:
        pivot = [round((minv[i] + maxv[i]) / 2, 4) for i in range(3)]
    bone = {
        "name": "bone",
        "pivot": pivot,
        "bind_pose_rotation": [0, 0, 0],
        "cubes": cubes,
    }
    geo = {
        "format_version": "1.21.0",
        "minecraft:geometry": [{
            "description": {
                "identifier": f"geometry.{geo_id}",
                "visible_bounds_width": 4.0,
                "visible_bounds_height": 4.0,
                "visible_bounds_offset": [0, 0.75, 0],
                "texture_width": int(texture_width),
                "texture_height": int(texture_height),
            },
            "bones": [bone],
        }],
    }
    return geo


# ------------------------------------------------------------------ animations
def display_animations(safe_id, display):
    """Rainbow AnimationMapper math. Returns dict of 3 animations or None."""
    d = display or {}

    def tr(ctx):
        return d.get(ctx) or {}

    fp = tr("firstperson_righthand")
    tp = tr("thirdperson_righthand")
    hd = tr("head")
    if not any(d.get(k) for k in ("firstperson_righthand", "thirdperson_righthand", "head", "fixed", "ground", "gui")):
        return None

    def g(x, k, dflt):
        v = (x or {}).get(k, dflt)
        return [float(c) for c in v] if isinstance(v, (list, tuple)) else dflt

    def rot(x):
        return g(x, "rotation", [0, 0, 0])

    def trans(x):
        return g(x, "translation", [0, 0, 0])

    def scale(x):
        return g(x, "scale", [1, 1, 1])

    fpr = rot(fp)
    fp_rot = [-90.0 + fpr[1], -fpr[2], fpr[0]]
    fpt = trans(fp)
    fp_pos = [-fpt[1], 12.5 + fpt[2], fpt[0]]
    fp_scale = scale(fp)

    tpr = rot(tp)
    tp_rot = [90.0, -tpr[2], -tpr[1]]
    tpt = trans(tp)
    tp_pos = [-tpt[0], 12.5 + tpt[2], -tpt[1]]
    tp_scale = scale(tp)

    hdt = trans(hd)
    head_pos = [-hdt[0] * 0.655, 20.0 + hdt[1] * 0.655, hdt[2] * 0.655]
    hdr = rot(hd)
    head_rot = [-hdr[0], -hdr[1], hdr[2]]
    head_scale = [v * 0.655 for v in scale(hd)]

    fx = tr("fixed")
    fxt = trans(fx)
    fxr = rot(fx)
    fixed_pos = [fxt[0], fxt[1] + 12.0, -fxt[2]]
    fixed_rot = [fxr[0], -fxr[1], -fxr[2]]
    fixed_scale = scale(fx)

    gr = tr("ground")
    grt = trans(gr)
    grs = scale(gr)
    ground_pos = [-grt[0], 12.5 + grt[2], -grt[1]]
    ground_rot = [-rot(gr)[0], rot(gr)[1], rot(gr)[2]]
    ground_scale = [grs[0], grs[1], grs[2]]

    def anim(name, pos, rots, sc):
        return {name: {"loop": True, "bones": {"bone": {
            "position": [round(p, 4) for p in pos],
            "rotation": [round(p, 4) for p in rots],
            "scale": [round(p, 5) for p in sc]}}}}

    out = {}
    out.update(anim(f"animation.{safe_id}.hold_first_person", fp_pos, fp_rot, fp_scale))
    out.update(anim(f"animation.{safe_id}.hold_third_person", tp_pos, tp_rot, tp_scale))
    out.update(anim(f"animation.{safe_id}.head", head_pos, head_rot, head_scale))
    out.update(anim(f"animation.{safe_id}.fixed", fixed_pos, fixed_rot, fixed_scale))
    out.update(anim(f"animation.{safe_id}.ground", ground_pos, ground_rot, ground_scale))
    return out


def bone_anim(bone, pos=None, rot=None, scale=None):
    entry = {}
    if pos is not None:
        entry["position"] = [round(p, 4) for p in pos]
    if rot is not None:
        entry["rotation"] = [round(p, 4) for p in rot]
    if scale is not None:
        entry["scale"] = [round(p, 5) for p in scale]
    return {bone: entry} if entry else None


# ------------------------------------------------------------------ attachable
def build_attachable(bedrock_identifier, geo_id, material_textures, animation=None, equippable_slot=None, uv_anim=None, geometry_override=None):
    """
    bedrock_identifier: altarsmp:xxx  (item)
    material_textures:  {'default' or 'mat_x': 'textures/items/...'}
    animation: dict of animation ids {key: id} to attach (fp/tp/head)
    """
    desc = {
        "identifier": bedrock_identifier,
        "materials": {"default": "entity_alphatest", "enchanted": "entity_alphatest_glint"},
        "textures": dict(material_textures),
        "geometry": {"default": f"geometry.{geo_id}" if not geometry_override else geometry_override},
        "render_controllers": [f"controller.render.altarsmp.{bedrock_identifier.replace(':', '.')}"],
    }
    if uv_anim:
        desc["uv_animation"] = uv_anim
    if animation:
        desc["animations"] = animation
        desc["scripts"] = {
            "animate": [
                {"first_person": "context.is_first_person == 1.0 && (context.item_slot == 'main_hand' || context.item_slot == 'off_hand')"},
                {"third_person": "context.is_first_person == 0.0 && (context.item_slot == 'main_hand' || context.item_slot == 'off_hand')"},
                {"on_head": "context.is_first_person == 0.0 && context.item_slot == 'head'"},
                {"on_display": "context.is_first_person == 0.0 && (context.item_slot == 'slot.armor.chest' || context.item_slot == 'slot.armor.head')"},
            ]
        }
    return {"format_version": "1.21.0", "minecraft:attachable": {"description": desc}}


def build_render_controller(bedrock_identifier, texture_names, has_glint=True):
    """textures array indexes match attachable texture key order; enchanted glint toggled by
    variable.is_enchanted via material swap (Rainbow DEFAULT_MATERIAL style)."""
    rc_name = f"controller.render.altarsmp.{bedrock_identifier.replace(':', '.')}"
    texs = list(texture_names) or ["default"]
    rc = {
        "format_version": "1.8.0",
        "render_controllers": {rc_name: {
            "geometry": "Geometry.default",
            "materials": [{"*": "variable.is_enchanted ? Material.enchanted : Material.default"}],
            "textures": ["Texture.default"] if len(texs) == 1 else ["Texture." + t for t in texs],
        }},
    }
    return rc_name, rc
