"""
Texture pipeline: copies the REAL AltarSMP artwork into Bedrock layout, stitches
multi-texture models into a single atlas (Rainbow's StitchedTextures idea), maps
Java animated .png.mcmeta -> Bedrock flipbook entries, and rasterises GUI icons
for 3D models using the model's own display.gui transform (exact Java semantics:
translate(t/16) * Rz*Ry*Rx(neg) * scale * translate(-0.5)).
"""

import json
import math
import os
from pathlib import Path

from PIL import Image

from .bedrock_model import VANILLA_GENERATED_ELEMENTS, _rotmat

TRANSPARENT_CACHE = {}


def transparent(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def load_png(path):
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def mcmeta_animation(path):
    p = str(path) + ".mcmeta"
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
        a = d.get("animation")
        if isinstance(a, dict):
            return a
    except Exception:
        return None
    return None


class TexStore:
    """Deduplicated texture copying into the Bedrock pack."""

    def __init__(self, rp_root, pack_root):
        self.rp = Path(rp_root)
        self.pack = Path(pack_root)
        self.consumed = {}   # texture id -> pack-relative path
        self.flips = {}       # pack path -> flipbook dict (atlas_tile filled later)
        self.meta = {}

    def source(self, tex_id):
        ns, _, p = str(tex_id).partition(":")
        if not p:
            ns, p = "minecraft", tex_id
        return self.rp / "assets" / ns / "textures" / (p + ".png")

    def has(self, tex_id):
        return self.source(tex_id).exists()

    def put(self, tex_id, dest_rel):
        """Copy one texture into the pack (nearest-resize to power-of-two only if needed)."""
        key = f"{tex_id}@{dest_rel}"
        if key in self.consumed:
            return self.consumed[key]
        src = self.source(tex_id)
        if not src.exists():
            return None
        out = self.pack / dest_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        img = load_png(src)
        if img is None:
            return None
        img.save(out)
        rel = dest_rel
        anim = mcmeta_animation(src)
        if anim:
            w, h = img.size
            nframes = max(1, h // w) if w else 1
            # Bedrock item-atlas flipbook entry (documented form):
            self.flips[rel] = {
                "atlas_tile": None,  # filled with item_texture key by pack writer
                "frame_time": anim.get("frametime", 1),
                "stop_at_frame": nframes,
                "source_width": w,
                "source_height": h,
                "frame_width": w,
                "frame_height": w,
            }
        self.consumed[key] = rel
        return rel


# ------------------------------------------------------------------ stitching
def stitch(timgs, size=16):
    """Horizontal atlas of RGBA images (already pixel-identical to sources)."""
    if len(timgs) == 1:
        return timgs[0][1], {}
    w = sum(im.size[0] for _, im in timgs)
    h = max(im.size[1] for _, im in timgs)
    canvas = transparent((w, h))
    offsets = {}
    x = 0
    for slot, im in timgs:
        canvas.paste(im, (x, 0))
        offsets[slot] = (x, 0, im.size[0], im.size[1])
        x += im.size[0]
    return canvas, offsets


# ------------------------------------------------------------------ icon raster
FACE_SHADE = {"up": 1.0, "down": 0.5, "north": 0.8, "south": 0.8, "east": 0.6, "west": 0.6}


def _clip(v, a, b):
    return a if v < a else (b if v > b else v)


def _sample(img, u, v):
    w, h = img.size
    x = int(u) % w if w else 0
    y = int(v) % h if h else 0
    return img.getpixel((x, y))


def _uv_rect(uv, size_wh):
    u1, v1, u2, v2 = [float(t) for t in uv]
    return min(u1, u2), min(v1, v2), abs(u2 - u1), abs(v2 - v1), (u2 < u1), (v2 < v1)


def _face_quad(face_name, fr, to):
    x1, y1, z1 = fr
    x2, y2, z2 = to
    if face_name == "down":   return [(x1, y1, z1), (x2, y1, z1), (x2, y1, z2), (x1, y1, z2)]
    if face_name == "up":     return [(x1, y2, z2), (x2, y2, z2), (x2, y2, z1), (x1, y2, z1)]
    if face_name == "north":  return [(x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1)]
    if face_name == "south":  return [(x2, y1, z2), (x1, y1, z2), (x1, y2, z2), (x2, y2, z2)]
    if face_name == "west":   return [(x1, y1, z2), (x1, y1, z1), (x1, y2, z1), (x1, y2, z2)]
    if face_name == "east":   return [(x2, y1, z1), (x2, y1, z2), (x2, y2, z2), (x2, y2, z1)]
    return None


def _face_uv_corners(face_name, u0, v0, uw, vh, flip_u, flip_v):
    """Map uv rect to the 4 quad corners in vanilla per-face order."""
    # base order matches _face_quad corners (BL, BR, TR, TL style per face)
    uu = [0, uw, uw, 0]
    vv = [0, 0, vh, vh]
    if face_name in ("up", "down"):
        uu = [0, uw, uw, 0]
        vv = [vh, vh, 0, 0]
    if flip_u:
        uu = [uw - u for u in uu]
    if flip_v:
        vv = [vh - v for v in vv]
    return [(u0 + a, v0 + b) for a, b in zip(uu, vv)]


def render_icon(model, texmap, gui_light="front", canvas=16, ss=4):
    """
    Rasterise a resolved java model to a PIL icon reproducing Java's GUI pass:
    orthographic camera, model-space transform
        p' = Rz*Ry*Rx(-angles) * ((p/16 - 0.5) * scale) + translation/16
    painter order by view depth; per-texel splatting with supersampling.
    texmap: slot -> (PIL image RGBA, texture_size float)
    """
    els = model.get("elements") or []
    display = (model.get("display") or {}).get("gui") or {}
    rot = [float(a) for a in display.get("rotation", [0, 0, 0])]
    trans = [float(v) for v in display.get("translation", [0, 0, 0])]
    scl = [float(v) for v in display.get("scale", [1, 1, 1])]
    R = _rotmat([-a for a in rot])
    tx, ty, tz = [v / 16.0 for v in trans]
    size = canvas * ss
    span = size / 1.35  # vanilla GUI fits ~74% of the slot for oversized safety

    def project(x, y, z):
        v = [(x / 16.0 - 0.5) * scl[0], (y / 16.0 - 0.5) * scl[1], (z / 16.0 - 0.5) * scl[2]]
        r = [R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
             R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
             R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2]]
        return (r[0] + tx) * span + size / 2.0, size / 2.0 - (r[1] + ty) * span, r[2] + tz

    faces = []
    for el in els:
        fr, to = [float(x) for x in el["from"]], [float(x) for x in el["to"]]
        for fname, face in (el.get("faces") or {}).items():
            if fname not in FACE_SHADE:
                continue
            tid = str(face.get("texture", "")).lstrip("#")
            tex = texmap.get(tid)
            if tex is None:
                for k, v in texmap.items():
                    if k == tid or v and getattr(v[0], "_tid", None) == tid:
                        tex = v
                        break
            if tex is None:
                continue
            quad = _face_quad(fname, fr, to)
            if not quad:
                continue
            uv = face.get("uv") or [0, 0, 16, 16]
            uvd = face.get("uv")
            if isinstance(uvd, dict):
                uv = uvd.get("uv", [0, 0, 16, 16])
            u1, v1, u2, v2 = [float(t) for t in uv]
            u0, w0 = min(u1, u2), min(v1, v2)
            uw, vh = abs(u2 - u1), abs(v2 - v1)
            if uw < 1e-6 or vh < 1e-6:
                uw, vh = max(uw, 0.25), max(vh, 0.25)
            pc = [project(*q) for q in quad]
            depth = sum(c[2] for c in pc) / 4.0
            faces.append((depth, fname, pc, uv, (u0, w0, uw, vh, u2 < u1, v2 < v1), tex, face))
    faces.sort(key=lambda f: f[0])  # far (small z) first

    buf = {}
    shade_on = (gui_light == "side")
    for depth, fname, pc, uv, (u0, v0, uw, vh, fu, fv), (tim, tsz), face in faces:
        w, h = tim.size
        su = w / max(tsz, 1e-9)   # exact vanilla mapping: pixel = uv(model space) * tex_px/texture_size
        sv = h / max(tsz, 1e-9)
        # sample one colour per uv texel; place at bilinear point of the projected quad
        nu = max(1, int(round(uw)))
        nv = max(1, int(round(vh)))
        A, B, C, D = pc
        for i in range(nu):
            for j in range(nv):
                s_ = (i + 0.5) / nu
                t_ = (j + 0.5) / nv
                uu = u0 + s_ * uw
                vv = v0 + t_ * vh
                col = tim.getpixel((int(uu * su) % tim.size[0], int(vv * sv) % tim.size[1]))
                if col[3] < 8:
                    continue
                top = [(A, D), (B, C)]
                p00 = _lerp(top[0][0], top[0][1], s_)
                p11 = _lerp(top[1][0], top[1][1], s_)
                p = _lerp(p00, p11, t_)
                z = p[2]
                dx, dy = int(p[0]), int(p[1])
                key = (dx, dy)
                prev = buf.get(key)
                if prev is not None and prev[0] > z:
                    continue
                sh = FACE_SHADE[fname] if shade_on else 1.0
                buf[key] = (z,
                            int(_clip(col[0] * sh, 0, 255)),
                            int(_clip(col[1] * sh, 0, 255)),
                            int(_clip(col[2] * sh, 0, 255)),
                            col[3])
    img = transparent((size, size))
    px = img.load()
    for (dx, dy), (_, r, g, b, a) in buf.items():
        if 0 <= dx < size and 0 <= dy < size:
            px[dx, dy] = (r, g, b, a)
    return img.resize((canvas, canvas), Image.NEAREST)


def _lerp(p, q, t):
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, p[2] + (q[2] - p[2]) * t)


def render_flat_icon(layers):
    """layers: list of PIL images already at icon size (layer0/layer1)."""
    if not layers:
        return None
    base = layers[0].copy()
    for im in layers[1:]:
        base.alpha_composite(im)
    return base
