#!/usr/bin/env python3
"""2D editorial motion graphics renderer for «Colombia: cuando la violencia se
volvió cotidiana». Every frame is drawn with Pillow/NumPy and piped to FFmpeg.

Inputs : production/timeline.json (from make_timeline.py), out/mezcla_sin_voz.wav
         assets/geo/*.json (Natural Earth, public domain)
         assets/archival/gaitan.jpg (optional: a verified archival photo)
Outputs: out/la_violencia_tiktok_1080x1920.mp4

Usage: render_video.py [--preview SECONDS ...] [--frames N] [--workers 4]
"""
import argparse
import json
import math
import subprocess
import sys
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "out"
TL = json.loads((ROOT / "production" / "timeline.json").read_text())
W, H, FPS = TL["width"], TL["height"], TL["fps"]
DUR = TL["duration"]

# ---------------------------------------------------------------- palette
BLACK = (11, 11, 11)
CHAR = (27, 27, 26)
CHAR2 = (40, 40, 38)
GRAY = (92, 91, 87)
GRAY2 = (146, 144, 138)
PAPER = (226, 219, 201)
PAPER_DIM = (196, 189, 171)
RED = (150, 22, 20)          # printing red: fills, rules, stamps
RED_TXT = (206, 46, 38)      # same hue, lifted for small text on black

# ---------------------------------------------------------------- cue times
LN = {l["id"]: l for l in TL["lines"]}


def ls(i):
    return LN[i]["start"]


def le(i):
    return LN[i]["end"]


S2 = ls("L03") - 0.2                 # tear: newspaper -> Bogotazo
FIRE = ls("L05") - 0.12              # «Bogotá arde»
S3 = ls("L06") - 0.15                # map
S4 = ls("L09") - 0.3                 # consequences
DISP = ls("L10") - 0.15              # displacement
FN = ls("L11") - 0.1                 # 1953-1958 timeline / Frente Nacional
PEND = ls("L12") - 0.05              # what remained unresolved
S5 = ls("L13") - 0.2                 # sixties
Q = ls("L14") - 0.1                  # closing question
TITLE = le("L14") + 0.1              # title card

# safe area for TikTok: keep essentials inside x 60..940, y 150..1480
SUB_Y = 1300


# ---------------------------------------------------------------- math
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def ramp(t, t0, t1):
    return clamp((t - t0) / (t1 - t0)) if t1 > t0 else float(t >= t0)


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_io(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def win(t, t0, t1, fin=0.35, fout=0.35):
    """1 inside [t0, t1] with eased fades at both ends."""
    return ease(ramp(t, t0, t0 + fin)) * (1 - ease(ramp(t, t1 - fout, t1)))


# ---------------------------------------------------------------- type
@lru_cache(maxsize=None)
def font(name, size, wght=None):
    f = ImageFont.truetype(str(FONTS / name), size)
    if wght is not None:
        f.set_variation_by_axes([wght])
    return f


def oswald(size, w=500):
    return font("Oswald[wght].ttf", size, w)


def bebas(size):
    return font("BebasNeue-Regular.ttf", size)


def serif(size, bold=True):
    return font("OldStandard-Bold.ttf" if bold else "OldStandard-Regular.ttf", size)


def typew(size):
    return font("SpecialElite-Regular.ttf", size)


@lru_cache(maxsize=512)
def text_img(text, fkey, size, fill, tracking=0, w=None):
    f = {"oswald": lambda: oswald(size, w or 500), "bebas": lambda: bebas(size),
         "serif": lambda: serif(size), "serif_r": lambda: serif(size, False),
         "typew": lambda: typew(size)}[fkey]()
    if tracking == 0:
        l, t, r, b = f.getbbox(text)
        im = Image.new("RGBA", (r - l + 8, b - t + 8), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4 - l, 4 - t), text, font=f, fill=fill)
        return im
    widths = [f.getlength(c) for c in text]
    tw = int(sum(widths) + tracking * (len(text) - 1)) + 8
    l, t, r, b = f.getbbox("ÁÉgjy" + text)
    im = Image.new("RGBA", (tw, b - t + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 4
    for c, cw in zip(text, widths):
        d.text((x, 4 - t), c, font=f, fill=fill)
        x += cw + tracking
    return im


def with_alpha(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def put(canvas, im, x, y, alpha=1.0, anchor="mm", scale=1.0, rot=0.0):
    if alpha <= 0.003:
        return
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BICUBIC)
    if rot:
        im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
    im = with_alpha(im, alpha)
    ax = {"l": 0, "m": 0.5, "r": 1}[anchor[0]]
    ay = {"t": 0, "m": 0.5, "b": 1}[anchor[1]]
    canvas.alpha_composite(im, (int(round(x - im.width * ax)), int(round(y - im.height * ay))))


def ss_draw(size, fn, factor=3):
    """Draw at `factor`x and downsample: anti-aliased vector shapes."""
    big = Image.new("RGBA", (size[0] * factor, size[1] * factor), (0, 0, 0, 0))
    fn(ImageDraw.Draw(big), factor)
    return big.resize(size, Image.LANCZOS)


def typed(text, progress):
    n = int(round(len(text) * clamp(progress)))
    return text[:n]


# ---------------------------------------------------------------- textures
def noise(w, h, cell, seed):
    rng = np.random.default_rng(seed)
    small = rng.random((max(2, h // cell), max(2, w // cell))).astype(np.float32)
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


@lru_cache(maxsize=None)
def paper(w, h, base, seed=1, strength=1.0):
    n = (noise(w, h, 3, seed) - 0.5) * 0.10 + (noise(w, h, 40, seed + 1) - 0.5) * 0.10 \
        + (noise(w, h, 180, seed + 2) - 0.5) * 0.07
    n *= strength
    arr = np.clip(np.array(base, np.float32)[None, None, :] * (1 + n[..., None]), 0, 255)
    return Image.fromarray(arr.astype(np.uint8)).convert("RGBA")


@lru_cache(maxsize=None)
def vignette():
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W / 2) / (W * 0.62)) ** 2 + ((y - H / 2) / (H * 0.6)) ** 2)
    v = np.clip(1.0 - 0.55 * np.clip(d - 0.55, 0, 1) ** 1.6, 0, 1)
    return v[..., None]


@lru_cache(maxsize=None)
def grain_frames():
    rng = np.random.default_rng(7)
    out = []
    for i in range(8):
        g = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
        g = np.asarray(Image.fromarray(((g * 32) + 128).clip(0, 255).astype(np.uint8))
                       .resize((W, H), Image.BILINEAR), np.float32) - 128
        out.append(g[..., None] / 128.0)
    return out


@lru_cache(maxsize=None)
def sub_band():
    """Soft dark band behind the subtitle zone so captions read on any scene."""
    a = np.zeros((H, W), np.float32)
    y = np.arange(H, dtype=np.float32)
    prof = np.clip(1 - np.abs(y - (SUB_Y + 20)) / 230, 0, 1) ** 1.4 * 0.72
    a[:] = prof[:, None]
    im = Image.new("RGBA", (W, H), BLACK + (0,))
    im.putalpha(Image.fromarray((a * 255).astype(np.uint8)))
    return im


def finish(canvas, t, fi):
    arr = np.asarray(canvas.convert("RGB"), np.float32)
    flick = 1 + 0.014 * math.sin(fi * 2.1) * math.sin(fi * 0.37)
    arr = arr * vignette() * flick
    arr += grain_frames()[fi % 8] * 9.0
    # sparse dust specks (deterministic per frame)
    rng = np.random.default_rng(fi * 31 + 5)
    if rng.random() < 0.35:
        for _ in range(rng.integers(1, 3)):
            x, y = rng.integers(40, W - 40), rng.integers(40, H - 40)
            r = int(rng.integers(1, 3))
            arr[y - r:y + r, x - r:x + r] = arr[y - r:y + r, x - r:x + r] * 0.4 + 0.6 * 200
    return np.clip(arr, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- small UI pieces
def kicker(canvas, text, x, y, alpha=1.0, color=GRAY2, size=30, anchor="lm", rule=True):
    im = text_img(text, "oswald", size, color, tracking=5, w=500)
    put(canvas, im, x, y, alpha, anchor)
    if rule:
        d = ImageDraw.Draw(canvas)
        x0 = x if anchor[0] == "l" else x - im.width / 2 if anchor[0] == "m" else x - im.width
        d.rectangle([x0 - 34, y - 2, x0 - 12, y + 2], fill=RED + (int(255 * alpha),))


def tag(canvas, text, x, y, alpha=1.0, size=22, fg=BLACK, bg=PAPER_DIM, anchor="lm"):
    im = text_img(text, "oswald", size, fg, tracking=3, w=600)
    box = Image.new("RGBA", (im.width + 18, im.height + 6), bg + (255,))
    box.alpha_composite(im, (9, 3))
    put(canvas, box, x, y, alpha, anchor)


def illus_tag(canvas, x, y, alpha=1.0, text="ILUSTRACIÓN · RECREACIÓN GRÁFICA"):
    tag(canvas, text, x, y, alpha * 0.9, size=19, fg=PAPER, bg=(60, 58, 55), anchor="lm")


def para(canvas, lines, x, y, size, color, alpha=1.0, w=400, lead=1.28, anchor="l", fkey="oswald"):
    for i, ln in enumerate(lines):
        im = text_img(ln, fkey, size, color, w=w) if fkey == "oswald" else text_img(ln, fkey, size, color)
        put(canvas, im, x, y + i * size * lead, alpha, anchor + "t")


# ---------------------------------------------------------------- subtitles
def rich_line(words, size):
    """words: list of (text, is_red). Returns RGBA image of one line."""
    f = oswald(size, 500)
    space = f.getlength(" ")
    asc, desc = f.getmetrics()
    wsum = int(sum(f.getlength(w) for w, _ in words) + space * (len(words) - 1)) + 16
    hmax = asc + desc + 8
    line = Image.new("RGBA", (wsum, hmax), (0, 0, 0, 0))
    d = ImageDraw.Draw(line)
    x = 8
    for txt, red in words:
        d.text((x, 4 + asc), txt, font=f, anchor="ls", fill=RED_TXT if red else (238, 233, 220))
        x += f.getlength(txt) + space
    # outline + soft shadow for contrast on any background
    a = line.getchannel("A")
    sh = Image.new("RGBA", (wsum + 24, hmax + 24), (0, 0, 0, 0))
    halo = a.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(3))
    sh.paste((0, 0, 0, 255), (12, 14), halo.point(lambda v: int(v * 0.85)))
    sh.alpha_composite(line, (12, 12))
    return sh


def tokens(text, red_phrases):
    """Split text into words, flagging those inside a red phrase."""
    flags = [False] * len(text)
    for ph in red_phrases:
        i = text.find(ph)
        while i >= 0:
            for k in range(i, i + len(ph)):
                flags[k] = True
            i = text.find(ph, i + 1)
    out, pos = [], 0
    for wd in text.split(" "):
        j = text.find(wd, pos)
        red = any(flags[j:j + len(wd)]) and all(flags[j:j + len(wd.strip(",.?¿;:"))])
        out.append((wd, red))
        pos = j + len(wd)
    return out


@lru_cache(maxsize=None)
def sub_image(text, red_key):
    red = list(red_key)
    size = 54
    toks = tokens(text, red)
    f = oswald(size, 500)
    maxw = 760
    lines, cur = [], []
    for tk in toks:
        trial = " ".join(w for w, _ in cur + [tk])
        if cur and f.getlength(trial) > maxw:
            lines.append(cur)
            cur = [tk]
        else:
            cur.append(tk)
    lines.append(cur)
    if len(lines) == 2 and len(lines[1]) == 1 and len(lines[0]) > 2:   # avoid orphans
        lines[1].insert(0, lines[0].pop())
    imgs = [rich_line(l, size) for l in lines[:2]]
    hh = sum(i.height for i in imgs) - 30 * (len(imgs) - 1)
    ww = max(i.width for i in imgs)
    out = Image.new("RGBA", (ww, hh), (0, 0, 0, 0))
    y = 0
    for im in imgs:
        out.alpha_composite(im, ((ww - im.width) // 2, y))
        y += im.height - 30
    return out


SUB_EVENTS = [(c["start"], c["show_end"], c["text"], tuple(l["red"])) for l in TL["lines"] for c in l["chunks"]]


def draw_subs(canvas, t):
    for t0, t1, txt, red in SUB_EVENTS:
        if t0 - 0.04 <= t <= t1:
            a = ease(ramp(t, t0 - 0.04, t0 + 0.1)) * (1 - ease(ramp(t, t1 - 0.1, t1)))
            dy = (1 - ease_out(ramp(t, t0 - 0.04, t0 + 0.25))) * 14
            put(canvas, sub_image(txt, red), 500, SUB_Y + dy, a, "mm")


# ---------------------------------------------------------------- map
LON0, LON1, LAT0, LAT1 = -80.2, -65.6, -5.2, 13.4
GEO = ROOT / "assets" / "geo"
SKIP = {"San Andrés y Providencia", None}
GROUPS = {
    "bogota": ["Bogota"],
    "nororiente": ["Boyacá", "Santander", "Norte de Santander"],
    "tolima": ["Tolima"],
    "occidente": ["Valle del Cauca", "Caldas", "Risaralda", "Quindío"],
    "antioquia": ["Antioquia"],
    "llanos": ["Meta", "Casanare", "Arauca"],
}
# region cards: (group, title, detail, card anchor x, y, side)  — positions at the base camera
REGION_CARDS = [
    ("nororiente", "BOYACÁ Y SANTANDERES", "Policía «chulavita» contra liberales", 668, 420, "l"),
    ("tolima", "TOLIMA", "Epicentro rural · zonas cafeteras", 70, 800, "l"),
    ("occidente", "VALLE Y VIEJO CALDAS", "«Pájaros»: sicarios conservadores", 70, 610, "l"),
    ("antioquia", "ANTIOQUIA", "Más dura en la periferia", 70, 430, "l"),
    ("llanos", "LLANOS ORIENTALES", "Guerrillas liberales · amnistía 1953", 668, 805, "l"),
]
# documented displacement: liberals of northern Boyacá fled to the llanero foothills (Acuña Rodríguez)
FLIGHT = [(-72.62, 6.30), (-72.35, 5.75), (-72.55, 5.15)]
BOGOTA_CITY = (-74.08, 4.61)
MARQUETALIA = (-75.80, 3.15)     # approx., Planadas (Tolima)
SAN_VICENTE = (-73.41, 6.88)     # San Vicente de Chucurí (Santander)
BASE_CAM = (-73.95, 4.15, 50.0)  # lon, lat, px per degree
CX, CY = 512, 700                # screen position of the camera centre


class Geo:
    def __init__(self):
        cols = json.loads((GEO / "col_adm1.json").read_text())["features"]
        nbs = json.loads((GEO / "neighbors.json").read_text())["features"]
        self.depts = {f["properties"]["name"]: shape(f["geometry"]) for f in cols
                      if f["properties"]["name"] not in SKIP}
        self.nbs = [shape(f["geometry"]) for f in nbs if f["properties"]["name"] != "COL"]
        self.levels = {}
        for wk in (40, 110, 300):
            self.levels[wk] = self.build(wk)

    @staticmethod
    def rings(g):
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        for p in polys:
            yield list(p.exterior.coords)

    def build(self, wk):
        w, h = int((LON1 - LON0) * wk), int((LAT1 - LAT0) * wk)

        def xy(c):
            return [((x - LON0) * wk, (LAT1 - y) * wk) for x, y in c]

        lw = max(1, wk // 70)
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        for g in self.nbs:
            for r in self.rings(g):
                d.polygon(xy(r), fill=(24, 24, 23, 255), outline=(52, 51, 49, 255))
        land = Image.new("L", (w, h), 0)
        dl = ImageDraw.Draw(land)
        for g in self.depts.values():
            for r in self.rings(g):
                dl.polygon(xy(r), fill=255)
        tex = paper(w, h, (70, 68, 63), seed=11, strength=1.6)
        base.paste(tex, (0, 0), land)
        d = ImageDraw.Draw(base)
        for g in self.depts.values():
            for r in self.rings(g):
                d.line(xy(r), fill=(112, 109, 102, 255), width=lw, joint="curve")
        coast = land.filter(ImageFilter.FIND_EDGES)
        if wk > 100:
            coast = coast.filter(ImageFilter.MaxFilter(3))
        base.paste((200, 193, 176, 255), (0, 0), coast)
        # feather the outer edge of the neighbouring countries so the map has no hard frame
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        edge = np.minimum.reduce([xx, w - 1 - xx, yy, h - 1 - yy]) / (0.09 * min(w, h))
        fa = np.asarray(base.getchannel("A"), np.float32) * np.clip(edge, 0, 1)
        fa = np.maximum(fa, np.asarray(land, np.float32))
        base.putalpha(Image.fromarray(fa.astype(np.uint8)))
        masks = {}
        for gname, names in GROUPS.items():
            m = Image.new("L", (w, h), 0)
            dm = ImageDraw.Draw(m)
            for n in names:
                for r in self.rings(self.depts[n]):
                    dm.polygon(xy(r), fill=255)
            masks[gname] = m
        return {"wk": wk, "base": base, "masks": masks}

    def centroid(self, group):
        from shapely.ops import unary_union
        u = unary_union([self.depts[n] for n in GROUPS[group]])
        p = u.representative_point() if group != "bogota" else u.centroid
        return p.x, p.y


GEO_DATA = None


def geo():
    global GEO_DATA
    if GEO_DATA is None:
        GEO_DATA = Geo()
    return GEO_DATA


def to_screen(lon, lat, cam):
    clon, clat, k = cam
    return CX + (lon - clon) * k, CY - (lat - clat) * k


def warp(img, wk, cam, mode=Image.BILINEAR):
    """Render a world-space layer for camera `cam` (affine output->input map)."""
    clon, clat, k = cam
    s = wk / k
    x0 = (clon - LON0) * wk - CX * s
    y0 = (LAT1 - clat) * wk - CY * s
    return img.transform((W, H), Image.AFFINE, (s, 0, x0, 0, s, y0), resample=mode)


def pick_level(k):
    g = geo()
    for wk in (40, 110, 300):
        if wk >= k * 0.9:
            return g.levels[wk]
    return g.levels[300]


def map_layer(canvas, cam, alpha=1.0, highlights=(), dim=0.0):
    """highlights: list of (group, amount 0..1, colour)."""
    lev = pick_level(cam[2])
    base = warp(lev["base"], lev["wk"], cam)
    if dim:
        base = Image.blend(base, Image.new("RGBA", (W, H), BLACK + (255,)), dim * 0.6)
        base.putalpha(warp(lev["base"].getchannel("A"), lev["wk"], cam))
    for grp, amt, col in highlights:
        if amt <= 0.01:
            continue
        m = warp(lev["masks"][grp], lev["wk"], cam)
        if amt < 0.999:   # ink spreading out from the region's centre
            cx, cy = to_screen(*geo().centroid(grp), cam)
            yy, xx = np.ogrid[0:H, 0:W]
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            radius = 30 + amt * 520 * (cam[2] / 50)
            spread = np.clip((radius - dist) / 60.0, 0, 1)
            m = Image.fromarray((np.asarray(m, np.float32) * spread * min(1, amt * 1.5)).astype(np.uint8))
        fill = Image.new("RGBA", (W, H), col + (0,))
        fill.putalpha(m.point(lambda v: int(v * 0.82)))
        base.alpha_composite(fill)
    put(canvas, base, 0, 0, alpha, "lt")


def map_labels(canvas, cam, alpha):
    if alpha <= 0:
        return
    for txt, lon, lat in (("MAR CARIBE", -76.6, 11.9), ("OCÉANO PACÍFICO", -78.6, 3.0),
                          ("VENEZUELA", -68.3, 8.9), ("ECUADOR", -78.3, -1.3),
                          ("PERÚ", -74.8, -3.6), ("BRASIL", -68.0, -1.6), ("PANAMÁ", -79.2, 8.9)):
        x, y = to_screen(lon, lat, cam)
        rot = 90 if txt == "OCÉANO PACÍFICO" else 0
        put(canvas, text_img(txt, "oswald", 20, (98, 96, 92), tracking=4, w=400), x, y, alpha, "mm", rot=rot)


def city_marker(canvas, lon, lat, cam, label, alpha, size=26, side="r", sub=None, pulse=0.0):
    x, y = to_screen(lon, lat, cam)
    d = ImageDraw.Draw(canvas)
    a = int(255 * alpha)
    if pulse:
        r = 10 + pulse * 30
        d.ellipse([x - r, y - r, x + r, y + r], outline=RED_TXT + (int(a * (1 - pulse)),), width=3)
    d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=PAPER + (a,), outline=BLACK + (a,), width=2)
    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=RED + (a,))
    im = text_img(label, "oswald", size, PAPER, tracking=2, w=600)
    if side == "r":
        put(canvas, im, x + 18, y - 2, alpha, "lm")
        if sub:
            put(canvas, text_img(sub, "oswald", int(size * 0.72), GRAY2, w=400), x + 18, y + size * 0.85, alpha, "lm")
    else:
        put(canvas, im, x - 18, y - 2, alpha, "rm")
        if sub:
            put(canvas, text_img(sub, "oswald", int(size * 0.72), GRAY2, w=400), x - 18, y + size * 0.85, alpha, "rm")


@lru_cache(maxsize=None)
def region_card(title, detail):
    t = text_img(title, "oswald", 30, PAPER, tracking=2, w=600)
    dt = text_img(detail, "oswald", 23, (200, 196, 186), w=400)
    w = max(t.width, dt.width) + 30
    h = t.height + dt.height + 8
    card = Image.new("RGBA", (w, h), (14, 14, 14, 228))
    ImageDraw.Draw(card).rectangle([0, 0, 5, h], fill=RED + (255,))
    card.alpha_composite(t, (16, 2))
    card.alpha_composite(dt, (16, t.height + 2))
    return card


def draw_region_card(canvas, grp, title, detail, x, y, cam, a):
    if a <= 0:
        return
    card = region_card(title, detail)
    x = min(x, 940 - card.width)
    cx, cy = to_screen(*geo().centroid(grp), cam)
    # leader line from card edge to region centre
    ex = x + card.width if x < cx else x
    d = ImageDraw.Draw(canvas)
    p = ease_out(a)
    lx, ly = ex + (cx - ex) * p, y + (cy - y) * p
    d.line([(ex, y), (lx, ly)], fill=PAPER_DIM + (int(200 * a),), width=2)
    d.ellipse([lx - 5, ly - 5, lx + 5, ly + 5], fill=PAPER + (int(255 * a),))
    put(canvas, card, x + (1 - ease_out(a)) * (-20 if x < cx else 20), y, a, "lm")


def dashed_arrow(canvas, pts, progress, alpha, color=PAPER):
    """Dashed path drawn up to `progress` with an arrow head."""
    if progress <= 0:
        return
    # resample polyline
    P = np.array(pts, np.float32)
    seg = np.sqrt(((P[1:] - P[:-1]) ** 2).sum(1))
    L = seg.sum() * progress
    d = ImageDraw.Draw(canvas)
    a = int(255 * alpha)
    dash, gap, pos = 16, 10, 0.0
    samples = []
    for i in range(len(seg)):
        n = max(2, int(seg[i] / 2))
        for k in range(n):
            samples.append((P[i] + (P[i + 1] - P[i]) * k / n, pos + seg[i] * k / n))
        pos += seg[i]
    samples = [(p, s) for p, s in samples if s <= L]
    for j in range(1, len(samples)):
        if (samples[j][1] % (dash + gap)) < dash:
            d.line([tuple(samples[j - 1][0]), tuple(samples[j][0])], fill=color + (a,), width=4)
    if len(samples) > 3:
        tip, back = samples[-1][0], samples[-4][0]
        ang = math.atan2(tip[1] - back[1], tip[0] - back[0])
        hl = 18
        p1 = (tip[0] - hl * math.cos(ang - 0.45), tip[1] - hl * math.sin(ang - 0.45))
        p2 = (tip[0] - hl * math.cos(ang + 0.45), tip[1] - hl * math.sin(ang + 0.45))
        d.polygon([tuple(tip), p1, p2], fill=color + (a,))


# ---------------------------------------------------------------- illustrations
@lru_cache(maxsize=None)
def newspaper_page():
    """A generic extra edition, clearly a graphic recreation: no real masthead, no invented copy."""
    pw, ph = 900, 1130
    pg = paper(pw, ph, PAPER, seed=3).copy()
    d = ImageDraw.Draw(pg)
    ink = (24, 23, 22, 255)
    d.rectangle([40, 40, pw - 40, 46], fill=ink)
    m = text_img("EDICIÓN EXTRAORDINARIA", "serif", 56, ink[:3])
    pg.alpha_composite(m, ((pw - m.width) // 2, 64))
    d.rectangle([40, 160, pw - 40, 163], fill=ink)
    dl = text_img("BOGOTÁ · VIERNES 9 DE ABRIL DE 1948", "oswald", 24, ink[:3], tracking=4, w=500)
    pg.alpha_composite(dl, ((pw - dl.width) // 2, 170))
    d.rectangle([40, 210, pw - 40, 211], fill=ink)
    rng = np.random.default_rng(4)
    # body columns as grey type bars (texture only, nothing legible is invented)
    for col in range(3):
        x0 = 60 + col * 270
        y = 835 if col else 835
        while y < ph - 60:
            ln = rng.integers(170, 235) if rng.random() > 0.12 else rng.integers(60, 140)
            d.rectangle([x0, y, x0 + ln, y + 7], fill=(120, 116, 106, 255))
            y += 15 if rng.random() > 0.08 else 32
    for col in (1, 2):
        d.line([(50 + col * 270, 830), (50 + col * 270, ph - 60)], fill=(150, 146, 136, 255), width=1)
    return pg


@lru_cache(maxsize=None)
def orator_illustration(w=330, h=420):
    """Ink silhouette of an orator at a radio microphone: a symbolic recreation, not a portrait."""
    def fn(d, f):
        ink = (22, 21, 20, 255)
        S = lambda pts: [(x * f, y * f) for x, y in pts]
        d.rectangle([0, 0, w * f, h * f], fill=(205, 198, 180, 255))
        # halftone dots background
        for yy in range(0, h, 12):
            for xx in range(0, w, 12):
                r = 1.3 + 2.6 * (yy / h)
                d.ellipse([(xx + 6 - r) * f, (yy + 6 - r) * f, (xx + 6 + r) * f, (yy + 6 + r) * f],
                          fill=(160, 154, 140, 255))
        # body / suit
        d.polygon(S([(70, 420), (88, 300), (125, 262), (165, 252), (205, 262), (240, 300), (262, 420)]), fill=ink)
        # raised arm (right) with clenched hand
        d.polygon(S([(212, 270), (236, 262), (282, 150), (300, 92), (282, 84), (258, 140)]), fill=ink)
        d.ellipse(S([(272, 58), (312, 100)]), fill=ink)
        # neck and head, slicked-back hair
        d.rectangle(S([(150, 222), (182, 262)]), fill=ink)
        d.ellipse(S([(126, 128), (204, 236)]), fill=ink)
        d.chord(S([(122, 118), (208, 196)]), 180, 360, fill=ink)
        # collar / tie highlight
        d.polygon(S([(152, 258), (166, 300), (180, 258)]), fill=(205, 198, 180, 255))
        d.polygon(S([(162, 268), (166, 330), (170, 268)]), fill=ink)
        # radio microphone on stand
        d.rounded_rectangle(S([(70, 210), (112, 268)]), radius=14 * f, fill=(60, 58, 54, 255),
                            outline=(205, 198, 180, 255), width=2 * f)
        for yy in range(218, 262, 8):
            d.line(S([(76, yy), (106, yy)]), fill=(205, 198, 180, 255), width=f)
        d.rectangle(S([(88, 268), (94, 420)]), fill=(60, 58, 54, 255))
    return ss_draw((w, h), fn)


@lru_cache(maxsize=None)
def archival_photo(w=330, h=420):
    p = ROOT / "assets" / "archival" / "gaitan.jpg"
    if not p.exists():
        return None
    im = Image.open(p).convert("L")
    r = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    im = im.crop(((im.width - w) // 2, 0, (im.width - w) // 2 + w, h))
    arr = np.asarray(im, np.float32) / 255
    col = (np.array(PAPER, np.float32) * arr[..., None] + np.array(BLACK, np.float32) * (1 - arr[..., None]))
    return Image.fromarray(col.astype(np.uint8)).convert("RGBA")


@lru_cache(maxsize=None)
def skyline():
    """1940s downtown in silhouette: generic recreation (no specific building is claimed)."""
    def fn(d, f):
        ink = (8, 8, 8, 255)
        rng = np.random.default_rng(48)
        x = 0
        while x < W:
            bw = int(rng.integers(70, 170))
            bh = int(rng.integers(220, 520))
            d.rectangle([x * f, (H - 560 - bh) * f, (x + bw) * f, (H - 400) * f], fill=ink)
            # cornice and windows (some lit by fire)
            d.rectangle([(x - 4) * f, (H - 560 - bh) * f, (x + bw + 4) * f, (H - 552 - bh) * f], fill=ink)
            for wy in range(H - 540 - bh, H - 600, 46):
                for wx in range(x + 14, x + bw - 18, 30):
                    if rng.random() < 0.55:
                        c = (130, 24, 20, 255) if rng.random() < 0.35 else (34, 32, 30, 255)
                        d.rectangle([wx * f, wy * f, (wx + 12) * f, (wy + 22) * f], fill=c)
            x += bw + int(rng.integers(0, 12))
        # church tower
        tx = 640
        d.rectangle([tx * f, (H - 1170) * f, (tx + 90) * f, (H - 400) * f], fill=ink)
        d.polygon([(tx * f, (H - 1170) * f), ((tx + 45) * f, (H - 1300) * f), ((tx + 90) * f, (H - 1170) * f)], fill=ink)
        d.rectangle([(tx + 43) * f, (H - 1350) * f, (tx + 47) * f, (H - 1300) * f], fill=ink)
        d.rectangle([(tx + 30) * f, (H - 1335) * f, (tx + 60) * f, (H - 1331) * f], fill=ink)
        # overturned tram (symbol of the riots)
        d.rounded_rectangle([140 * f, (H - 470) * f, 470 * f, (H - 400) * f], radius=18 * f, fill=ink)
        for k in range(6):
            d.rectangle([(160 + k * 50) * f, (H - 458) * f, (190 + k * 50) * f, (H - 432) * f],
                        fill=(120, 22, 18, 255))
        d.rectangle([0, (H - 400) * f, W * f, H * f], fill=ink)
    return ss_draw((W, H), fn, factor=2)


@lru_cache(maxsize=None)
def fire_noise():
    return [noise(W // 4, H // 4, 18, 100 + i) for i in range(4)]


def fire_glow(t, intensity=1.0):
    fr = fire_noise()
    k = (t * 1.7) % 4
    i0, fpart = int(k), k - int(k)
    n = fr[i0] * (1 - fpart) + fr[(i0 + 1) % 4] * fpart
    y = np.linspace(0, 1, H // 4, dtype=np.float32)[:, None]
    prof = np.clip((y - 0.25) / 0.55, 0, 1) ** 1.3
    shift = int((t * 40) % (H // 4))
    n = np.roll(n, -shift, axis=0)
    g = np.clip(prof * (0.45 + 0.8 * n) * intensity, 0, 1)
    rgb = np.stack([g * 190, g * 32, g * 26], -1)
    rgb += (np.clip(g - 0.72, 0, 1) * 300)[..., None] * np.array([0.25, 0.22, 0.2])
    im = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    return im.convert("RGBA")


EMB = np.random.default_rng(9).random((70, 4))


def embers(canvas, t, alpha):
    d = ImageDraw.Draw(canvas)
    for x0, sp, ph, sz in EMB:
        life = (t * (0.25 + sp * 0.35) + ph) % 1.0
        x = x0 * W + 40 * math.sin(t * 1.3 + ph * 9)
        y = H - 420 - life * 1100
        a = int(255 * alpha * (1 - life) * 0.9)
        r = 1.5 + sz * 3
        d.ellipse([x - r, y - r, x + r, y + r], fill=(235, 214, 190, a) if sz > 0.6 else RED_TXT + (a,))


@lru_cache(maxsize=None)
def countryside():
    """Rural road at dusk: abandoned house, fence, mountains (symbolic recreation)."""
    def fn(d, f):
        ink = (12, 12, 12, 255)
        S = lambda pts: [(x * f, y * f) for x, y in pts]
        d.polygon(S([(0, 1060), (160, 930), (330, 1000), (520, 880), (760, 990), (1080, 900), (1080, 1200), (0, 1200)]),
                  fill=(36, 36, 34, 255))
        d.polygon(S([(0, 1120), (240, 1040), (480, 1090), (760, 1030), (1080, 1080), (1080, 1300), (0, 1300)]),
                  fill=(22, 22, 21, 255))
        d.rectangle(S([(0, 1180), (1080, 1920)]), fill=ink)
        # house with open door, roof, no light
        d.polygon(S([(120, 1180), (120, 1060), (205, 1000), (290, 1060), (290, 1180)]), fill=ink)
        d.polygon(S([(100, 1066), (205, 990), (310, 1066), (300, 1074), (205, 1004), (110, 1074)]), fill=(52, 50, 47, 255))
        d.rectangle(S([(186, 1110), (222, 1180)]), fill=(46, 44, 41, 255))
        d.polygon(S([(222, 1110), (246, 1120), (246, 1186), (222, 1180)]), fill=ink)
        # broken fence
        for i in range(9):
            x = 330 + i * 46
            hgt = 52 if i % 3 else 30
            d.rectangle(S([(x, 1180 - hgt), (x + 7, 1182)]), fill=ink)
        d.line(S([(330, 1150), (520, 1145)]), fill=ink, width=4 * f)
        d.line(S([(570, 1152), (700, 1158)]), fill=ink, width=4 * f)
        # road toward the horizon
        d.polygon(S([(470, 1920), (640, 1920), (560, 1180), (535, 1180)]), fill=(30, 30, 29, 255))
    return ss_draw((W, H), fn, factor=2)


def walkers(canvas, t, alpha):
    """Small figures walking along the road, receding: a family leaving."""
    d = ImageDraw.Draw(canvas)
    a = int(255 * alpha)
    for i, (ox, sc) in enumerate(((0, 1.0), (32, 0.92), (58, 0.62), (84, 1.04), (118, 0.85))):
        prog = (t * 0.035 + i * 0.012)
        y = 1330 - prog * 260 + (i % 2) * 6
        s = sc * (1.0 - prog * 0.6) * 1.15
        x = 600 - prog * 60 + ox * (1 - prog * 0.6)
        bob = math.sin(t * 6 + i * 1.7) * 2 * s
        hh = 64 * s
        d.ellipse([x - 6 * s, y - hh - 14 * s + bob, x + 6 * s, y - hh - 2 * s + bob], fill=(150, 146, 138, a))
        d.polygon([(x - 9 * s, y - hh + bob), (x + 9 * s, y - hh + bob), (x + 7 * s, y - 18 * s), (x - 7 * s, y - 18 * s)],
                  fill=(150, 146, 138, a))
        st = math.sin(t * 6 + i * 1.7) * 6 * s
        d.line([(x - 3 * s, y - 18 * s), (x - 4 * s + st, y)], fill=(150, 146, 138, a), width=max(2, int(4 * s)))
        d.line([(x + 3 * s, y - 18 * s), (x + 4 * s - st, y)], fill=(150, 146, 138, a), width=max(2, int(4 * s)))
        if i in (0, 3):   # bundle on the back
            d.ellipse([x + 4 * s, y - hh + 4 * s + bob, x + 20 * s, y - hh + 26 * s + bob], fill=(110, 106, 100, a))


@lru_cache(maxsize=None)
def stamp(text, size, color=RED, rot=-4):
    im = text_img(text, "bebas", size, color, tracking=4)
    pad = 26
    box = Image.new("RGBA", (im.width + pad * 2, im.height + pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(box)
    d.rectangle([4, 4, box.width - 5, box.height - 5], outline=color + (255,), width=6)
    box.alpha_composite(im, (pad, pad // 2))
    # ink wear: knock out speckles
    n = noise(box.width, box.height, 3, size) > 0.82
    a = np.asarray(box.getchannel("A"), np.float32)
    a[n] *= 0.25
    box.putalpha(Image.fromarray(a.astype(np.uint8)))
    return box.rotate(rot, resample=Image.BICUBIC, expand=True)


# ---------------------------------------------------------------- scenes
def bg(canvas, color=CHAR, seed=2, alpha=1.0, dy=0):
    """Scene background: a sheet that can fade in or slide over the previous scene."""
    put(canvas, paper(W, H, color, seed=seed, strength=1.3), 0, int(dy), alpha, "lt")


def scene1(c, t):
    """EL QUIEBRE: 1948, the partisan divide, the 9 April newspaper."""
    bg(c, CHAR)
    l2 = ls("L02")
    # 1948 stamped big, then shrinks to the top as a kicker
    s = ease_io(ramp(t, 1.15, 1.9))
    a = ease(ramp(t, 0.15, 0.3)) * (1 - ease(ramp(t, l2 - 0.2, l2 + 0.2)))
    sc = (1.18 - 0.18 * ease_out(ramp(t, 0.15, 0.42))) * (1 - 0.62 * s)
    put(c, text_img("1948", "bebas", 400, RED), W / 2 - 40 * s, 560 - 330 * s, a, "mm", scale=sc)
    put(c, text_img("COLOMBIA", "oswald", 34, GRAY2, tracking=12, w=500), W / 2, 330 - 120 * s,
        ease(ramp(t, 0.5, 0.9)) * (1 - ease(ramp(t, 1.15, 1.4))), "mm")
    # two parties
    l1b = ls("L01") + 0.9
    pa = ease_out(ramp(t, l1b, l1b + 0.6))
    pb = ease_out(ramp(t, l1b + 0.35, l1b + 0.95))
    out = 1 - ease(ramp(t, l2 - 0.1, l2 + 0.35))
    put(c, text_img("LIBERALES", "bebas", 170, PAPER, tracking=3), W / 2 - 260 * (1 - pa), 590, pa * out, "mm")
    put(c, text_img("CONSERVADORES", "bebas", 170, GRAY2, tracking=3), W / 2 + 260 * (1 - pb), 790, pb * out, "mm")
    rr = ease_out(ramp(t, l1b + 0.7, l1b + 1.3))
    d = ImageDraw.Draw(c)
    d.rectangle([W / 2 - 380 * rr, 686, W / 2 + 380 * rr, 693], fill=RED + (int(255 * out),))
    para(c, ["Desde 1946, con el regreso conservador al poder,",
             "ya había violencia partidista en regiones",
             "como Boyacá y los Santanderes."],
         W / 2, 905, 30, (190, 186, 176), ease(ramp(t, l1b + 1.4, l1b + 1.9)) * out, w=400, anchor="m")
    # newspaper slides up
    p = ease_out(ramp(t, l2 - 0.25, l2 + 0.5))
    if p > 0:
        pg = newspaper_page().copy()
        pp = ImageDraw.Draw(pg)
        # headline typed in, as a recreation
        hl = typed("ASESINADO GAITÁN", ramp(t, l2 + 0.25, l2 + 0.75))
        if hl:
            im = text_img(hl, "bebas", 148, (20, 19, 18), tracking=1)
            full = text_img("ASESINADO GAITÁN", "bebas", 148, (20, 19, 18), tracking=1)
            pg.alpha_composite(im, ((pg.width - full.width) // 2, 230))
        pp.rectangle([40, 392, 860, 394], fill=(24, 23, 22, 255))
        photo = archival_photo() or orator_illustration()
        pg.alpha_composite(photo, (60, 412))
        name_a = ease(ramp(t, ls("L02") + 1.9, ls("L02") + 2.4))
        nm = text_img("JORGE ELIÉCER", "bebas", 92, (20, 19, 18))
        nm2 = text_img("GAITÁN", "bebas", 150, RED)
        pg.alpha_composite(with_alpha(nm, name_a), (420, 430))
        pg.alpha_composite(with_alpha(nm2, name_a), (414, 520))
        for i, ln in enumerate(["Jefe del Partido Liberal desde 1947.", "Abogado y orador: movilizó a",
                                "trabajadores y sectores populares."]):
            pg.alpha_composite(with_alpha(text_img(ln, "serif_r", 27, (40, 38, 35)), name_a), (422, 690 + i * 36))
        if archival_photo() is None:
            pg.alpha_composite(with_alpha(text_img("ILUSTRACIÓN SIMBÓLICA · NO ES UN RETRATO", "oswald", 16,
                                                   (60, 58, 54), tracking=2, w=500), 1), (64, 794))
        push = 1 + 0.035 * ease(ramp(t, l2, S2))          # slow push-in until the tear
        y = H + 40 - (H + 40 - 690) * p
        rot = 1.6 * (1 - p) - 0.8
        put(c, pg, W / 2, y, 1.0, "mm", rot=rot, scale=0.86 * push)
        # red date stamp, over the body columns
        st_t = l2 + 0.15
        sa = ease(ramp(t, st_t, st_t + 0.08))
        ssc = 1.35 - 0.35 * ease_out(ramp(t, st_t, st_t + 0.18))
        put(c, stamp("9 DE ABRIL DE 1948", 80), 600, y + 330, sa, "mm", scale=ssc * push)
        illus_tag(c, 70, y + 520, ease(ramp(t, l2 + 0.6, l2 + 1.0)), "RECREACIÓN GRÁFICA · NO ES UN DOCUMENTO DE ARCHIVO")


def scene2(c, t):
    """EL BOGOTAZO: facts vs. open questions, then the burning city."""
    bg(c, BLACK, seed=5)
    # opening: the page tears apart (top half up, bottom half down)
    tt = ramp(t, S2, S2 + 0.55)
    if tt < 1:
        pg = newspaper_page()
        top = pg.crop((0, 0, pg.width, 560))
        bot = pg.crop((0, 560, pg.width, pg.height))
        e = ease_io(tt)
        k = 0.86 * 1.035
        put(c, top, W / 2, 690 - 285 * k - e * 900, 1, "mm", rot=-0.8 - 4 * e, scale=k)
        put(c, bot, W / 2, 690 + 285 * k + e * 1000, 1, "mm", rot=-0.8 + 5 * e, scale=k)
        d = ImageDraw.Draw(c)
        rng = np.random.default_rng(3)
        ys = 690 + (rng.random(30) - 0.5) * 30
        pts = [(i * W / 29, ys[i]) for i in range(30)]
        d.line(pts, fill=RED + (int(255 * (1 - e)),), width=6)
    a = ease(ramp(t, S2 + 0.25, S2 + 0.6)) * (1 - ease(ramp(t, FIRE - 0.25, FIRE)))
    if a > 0:
        loc = "BOGOTÁ · CARRERA SÉPTIMA CON AVENIDA JIMÉNEZ"
        put(c, text_img(typed(loc, ramp(t, S2 + 0.3, S2 + 1.3)) or " ", "typew", 30, PAPER), 70, 300, a, "lm")
        put(c, text_img(typed("9 DE ABRIL · POCO DESPUÉS DE LA 1 P. M.", ramp(t, S2 + 1.2, S2 + 1.9)) or " ",
                        "typew", 30, RED_TXT), 70, 348, a, "lm")
        d = ImageDraw.Draw(c)
        d.rectangle([70, 392, 940, 394], fill=GRAY + (int(255 * a),))
        # documented
        a1 = a * ease(ramp(t, ls("L03"), ls("L03") + 0.35))
        tag(c, "DOCUMENTADO", 70, 470, a1, size=24, fg=BLACK, bg=PAPER)
        para(c, ["Juan Roa Sierra, señalado como el tirador,", "fue linchado por la multitud.",
                 "Gaitán murió esa tarde en la Clínica Central."],
             70, 505, 38, PAPER, a1, w=400)
        # unresolved
        a2 = a * ease(ramp(t, ls("L04"), ls("L04") + 0.35))
        tag(c, "SIN ESCLARECER", 70, 728, a2, size=24, fg=PAPER, bg=RED)
        para(c, ["¿Actuó solo? ¿Hubo autores intelectuales?", "Hay muchas hipótesis; ninguna se ha probado."],
             70, 765, 38, (200, 196, 186), a2, w=400)
        # question marks slowly pulse on the red rule
        q = 0.5 + 0.5 * math.sin(t * 3)
        d.rectangle([70, 885, 70 + 870 * ease_out(ramp(t, ls("L04") + 0.3, ls("L04") + 1.6)), 888],
                    fill=RED + (int(255 * a2 * (0.6 + 0.4 * q)),))
    # the city burns
    fa = ease(ramp(t, FIRE - 0.08, FIRE + 0.12)) * (1 - ease(ramp(t, S3 + 0.2, S3 + 0.7)))
    if fa > 0:
        layer = Image.new("RGBA", (W, H), BLACK + (255,))
        layer.alpha_composite(fire_glow(t, 0.75 + 0.25 * ease(ramp(t, FIRE, FIRE + 0.6))))
        drift = (t - FIRE) * 10
        layer.alpha_composite(skyline(), (0, int(-drift)))
        embers(layer, t, 1)
        sc = 1.12 - 0.12 * ease_out(ramp(t, FIRE, FIRE + 0.4))
        put(layer, text_img("EL BOGOTAZO", "bebas", 190, PAPER, tracking=4), W / 2, 330, 1, "mm", scale=sc)
        d = ImageDraw.Draw(layer)
        rr = ease_out(ramp(t, FIRE + 0.15, FIRE + 0.6))
        d.rectangle([W / 2 - 330 * rr, 432, W / 2 + 330 * rr, 439], fill=RED + (255,))
        para(layer, ["Incendios, saqueos y destrucción en el centro.",
                     "Víctimas: no hay cifra fiable (se estiman de cientos a miles)."],
             W / 2, 470, 28, (220, 214, 200), ease(ramp(t, FIRE + 0.4, FIRE + 0.8)), w=400, anchor="m")
        illus_tag(layer, 70, 1150, 1.0)
        put(c, layer, 0, 0, fa, "lt")


def map_cam(t):
    """Bogotá close-up -> whole country."""
    z = ease_io(ramp(t, S3 + 0.2, S3 + 2.6))
    bl, bt, bk = BOGOTA_CITY[0], BOGOTA_CITY[1], 260.0
    lon = bl + (BASE_CAM[0] - bl) * z
    lat = bt + (BASE_CAM[1] - bt) * z
    k = math.exp(math.log(bk) + (math.log(BASE_CAM[2]) - math.log(bk)) * z)
    return lon, lat, k


REGION_T = None


def region_times():
    global REGION_T
    if REGION_T is None:
        t0 = ls("L07") - 0.1
        step = (ls("L08") + 1.0 - t0) / len(REGION_CARDS)
        REGION_T = [t0 + i * step for i in range(len(REGION_CARDS))]
    return REGION_T


def scene3(c, t):
    """DEL CENTRO A LAS REGIONES."""
    bg(c, BLACK, seed=8, alpha=ease(ramp(t, S3 - 0.1, S3 + 0.3)))
    cam = map_cam(t)
    out = 1 - ease(ramp(t, S4 - 0.1, S4 + 0.4))
    fade_in = ease(ramp(t, S3 - 0.1, S3 + 0.4))
    hl = [("bogota", 1.0 * ease(ramp(t, S3, S3 + 0.5)), RED)]
    for (grp, *_), rt in zip(REGION_CARDS, region_times()):
        hl.append((grp, ramp(t, rt, rt + 0.9), RED))
    map_layer(c, cam, fade_in * out, hl)
    full = ease(ramp(t, S3 + 1.6, S3 + 2.6))
    map_labels(c, cam, full * out * 0.9)
    city_marker(c, *BOGOTA_CITY, cam, "BOGOTÁ", fade_in * out, size=40 - 12 * full, side="r",
                sub="9 de abril de 1948" if full < 0.5 else None)
    # headline
    ha = ease(ramp(t, ls("L06") + 1.9, ls("L06") + 2.3)) * out
    put(c, text_img("LA VIOLENCIA", "bebas", 130, PAPER, tracking=4), 70, 200, ha, "lm")
    put(c, text_img("c. 1948 – 1958*", "oswald", 34, RED_TXT, tracking=3, w=500), 74, 275, ha, "lm")
    for i, (grp, title, detail, x, y, side) in enumerate(REGION_CARDS):
        rt = region_times()[i]
        draw_region_card(c, grp, title, detail, x, y, cam, ease(ramp(t, rt + 0.15, rt + 0.6)) * out)
    # documented flight route, northern Boyacá -> llanero foothills
    rt0 = region_times()[0]
    fp = ease_io(ramp(t, rt0 + 0.5, rt0 + 1.6))
    pts = [to_screen(lo, la, cam) for lo, la in FLIGHT]
    dashed_arrow(c, pts, fp, out * 0.95)
    # legend + notes
    la_ = ease(ramp(t, rt0 + 0.9, rt0 + 1.3)) * out
    d = ImageDraw.Draw(c)
    for k in range(3):
        d.line([(70 + k * 18, 1108), (80 + k * 18, 1108)], fill=PAPER + (int(255 * la_),), width=4)
    put(c, text_img("Desplazamiento documentado: liberales del norte de Boyacá huyen al piedemonte llanero",
                    "oswald", 20, (200, 196, 186), w=400), 132, 1108, la_, "lm")
    na = ease(ramp(t, region_times()[-1] + 0.6, region_times()[-1] + 1.0)) * out
    put(c, text_img("Límites departamentales actuales, como referencia: en 1948 el Viejo Caldas incluía",
                    "oswald", 19, GRAY2, w=400), 70, 1140, na, "lm")
    put(c, text_img("Risaralda y Quindío, y los Llanos tenían otra división. *La periodización varía según los autores.",
                    "oswald", 19, GRAY2, w=400), 70, 1166, na, "lm")


def scene4(c, t):
    """LAS CONSECUENCIAS: estimates, displacement, amnesty, Frente Nacional, what stayed open."""
    enter = ease_out(ramp(t, S4 - 0.1, S4 + 0.45))
    bg(c, CHAR, seed=12, dy=H * (1 - enter))          # a new page slides up over the map
    if enter < 1:
        ImageDraw.Draw(c).rectangle([0, H * (1 - enter) - 4, W, H * (1 - enter)], fill=RED + (255,))
    # --- A: death estimates
    aA = ease(ramp(t, S4 + 0.2, S4 + 0.5)) * (1 - ease(ramp(t, DISP - 0.45, DISP - 0.15)))
    if aA > 0:
        kicker(c, "MUERTES ESTIMADAS · LA VIOLENCIA", 110, 250, aA, size=30)
        put(c, text_img("¿CUÁNTOS?", "bebas", 150, PAPER, tracking=3), 76, 345, aA, "lm")
        x0, x1, y = 90, 920, 700
        maxv = 220000
        X = lambda v: x0 + (x1 - x0) * v / maxv
        d = ImageDraw.Draw(c)
        a8 = int(255 * aA)
        d.line([(x0, y), (x1, y)], fill=GRAY2 + (a8,), width=3)
        for v in range(0, maxv + 1, 50000):
            d.line([(X(v), y - 10), (X(v), y + 10)], fill=GRAY2 + (a8,), width=2)
            put(c, text_img(f"{v // 1000}k" if v else "0", "oswald", 22, GRAY2, w=400), X(v), y + 34, aA, "mm")
        marks = [(57737, "≈ 57.700", "Romero y Meisel", "Banco de la República, 2019 · 1949–58", 0),
                 (134820, "≈ 134.800", "Guzmán, Fals Borda y Umaña", "La Violencia en Colombia, 1962 · 1949–58", 1),
                 (200000, "≈ 200.000", "Cifra más difundida", "Varias síntesis históricas", 2)]
        t0 = ls("L09") + 0.3
        band = ease_out(ramp(t, t0, t0 + 2.6))
        d.rectangle([X(40000), y - 6, X(40000) + (X(205000) - X(40000)) * band, y + 6], fill=RED + (a8,))
        for v, num, who, ref, i in marks:
            ma = aA * ease(ramp(t, t0 + i * 0.85, t0 + i * 0.85 + 0.3))
            if ma <= 0:
                continue
            up = i % 2 == 0
            yy = y - 70 if up else y + 90
            d.line([(X(v), y), (X(v), yy + (30 if up else -30))], fill=PAPER + (int(255 * ma),), width=2)
            d.ellipse([X(v) - 7, y - 7, X(v) + 7, y + 7], fill=PAPER + (int(255 * ma),))
            anc = "r" if i == 2 else "l"
            xx = X(v) + (8 if anc == "l" else -8)
            if i == 0:
                xx = X(v) - 30
            put(c, text_img(num, "bebas", 56, PAPER, tracking=1), xx, yy - (20 if up else -10), ma, anc + "m")
            put(c, text_img(who, "oswald", 23, (215, 210, 198), w=600), xx, yy + (18 if up else 48), ma, anc + "m")
            put(c, text_img(ref, "oswald", 19, GRAY2, w=400), xx, yy + (44 if up else 74), ma, anc + "m")
        para(c, ["Las cifras dependen del método y del periodo.",
                 "Son de todo el periodo, no del Bogotazo."],
             90, 930, 27, GRAY2, aA * ease(ramp(t, t0 + 2.4, t0 + 2.8)), w=400)
    # --- B: displacement
    aB = ease(ramp(t, DISP - 0.15, DISP + 0.2)) * (1 - ease(ramp(t, FN - 0.45, FN - 0.15)))
    if aB > 0:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sky = paper(W, H, (44, 43, 41), seed=21, strength=1.2)
        layer.alpha_composite(sky)
        drift = (t - DISP) * 6
        layer.alpha_composite(countryside(), (int(-drift), 0))
        walkers(layer, t - DISP, 1.0)
        kicker(layer, "DESPLAZAMIENTO", 110, 250, 1.0, size=30)
        put(layer, text_img("HUIR DEL CAMPO", "bebas", 128, PAPER, tracking=3), 76, 336, 1, "lm")
        para(layer, ["Familias campesinas abandonan tierras y casas;", "muchas terminan en las ciudades."],
             80, 420, 32, (215, 210, 198), 1, w=400)
        para(layer, ["Estimación citada con frecuencia: hasta ≈ 2 millones", "de desplazados (P. Oquist, 1978)."],
             80, 520, 25, GRAY2, ease(ramp(t, DISP + 0.5, DISP + 0.9)), w=400)
        illus_tag(layer, 70, 1150, 1.0)
        put(c, layer, 0, 0, aB, "lt")
    # --- C/D: 1953 -> 1958 and what stayed open
    aC = ease(ramp(t, FN - 0.15, FN + 0.2)) * (1 - ease(ramp(t, S5 - 0.2, S5 + 0.25)))
    if aC > 0:
        d = ImageDraw.Draw(c)
        kicker(c, "PACIFICAR SIN RESOLVER", 110, 250, aC, size=30)
        x0, x1, y = 110, 880, 420
        lp = ease_out(ramp(t, FN, FN + 1.6))
        d.line([(x0, y), (x0 + (x1 - x0) * lp, y)], fill=GRAY2 + (int(255 * aC),), width=3)
        events = [(0.0, "1953", ["Golpe de Rojas Pinilla.", "Amnistía: guerrillas", "liberales entregan armas."]),
                  (0.5, "1957", ["Cae Rojas.", "Junta Militar."]),
                  (1.0, "1958", ["FRENTE NACIONAL"])]
        for i, (fx, yr, txt) in enumerate(events):
            ea = aC * ease(ramp(t, FN + i * 0.6, FN + i * 0.6 + 0.3))
            if ea <= 0:
                continue
            x = x0 + (x1 - x0) * fx
            col = RED if yr == "1958" else PAPER
            d.ellipse([x - 10, y - 10, x + 10, y + 10], fill=col + (int(255 * ea),))
            anc = "m" if 0 < fx < 1 else ("l" if fx == 0 else "r")
            put(c, text_img(yr, "bebas", 74, RED_TXT if yr == "1958" else PAPER), x, y - 58, ea, anc + "m")
            if yr != "1958":
                para(c, txt, x - (0 if anc == "l" else 0), y + 30, 24, (205, 200, 188), ea, w=400, anchor=anc)
        # Frente Nacional diagram
        fa = aC * ease(ramp(t, FN + 1.4, FN + 1.8))
        if fa > 0:
            ssc = 1.25 - 0.25 * ease_out(ramp(t, FN + 1.4, FN + 1.6))
            put(c, stamp("FRENTE NACIONAL", 96), W / 2 - 20, 640, fa, "mm", scale=ssc)
            by = 760
            cols = [("LIBERAL", PAPER), ("CONSERVADOR", GRAY2)]
            for i in range(4):
                bx = 110 + i * 200
                pa = fa * ease(ramp(t, FN + 1.7 + i * 0.15, FN + 1.95 + i * 0.15))
                name, colr = cols[i % 2]
                d.rectangle([bx, by, bx + 186, by + 70], fill=colr + (int(255 * pa),))
                put(c, text_img(name, "oswald", 24, BLACK, tracking=2, w=600), bx + 93, by + 35, pa, "mm")
            put(c, text_img("1958–1974 · la presidencia se alterna y los cargos se reparten por mitades",
                            "oswald", 23, (205, 200, 188), w=400), 110, by + 100, fa, "lm")
            put(c, text_img("Aprobado en el plebiscito de diciembre de 1957 · otras fuerzas quedan fuera",
                            "oswald", 21, GRAY2, w=400), 110, by + 132, fa, "lm")
        # unresolved
        pa_ = aC * ease(ramp(t, PEND + 0.2, PEND + 0.6))
        if pa_ > 0:
            d.rectangle([110, 945, 110 + 770 * ease_out(ramp(t, PEND + 0.2, PEND + 0.9)), 948],
                        fill=RED + (int(255 * aC),))
            tag(c, "SIGUE PENDIENTE", 110, 985, pa_, size=24, fg=PAPER, bg=RED)
            for i, ln in enumerate(["La tierra: concentración, despojo, colonos sin títulos.",
                                    "La exclusión política de quienes no eran liberales ni conservadores.",
                                    "Violencia rural y bandolerismo hasta mediados de los sesenta."]):
                la = aC * ease(ramp(t, PEND + 0.5 + i * 0.45, PEND + 0.85 + i * 0.45))
                put(c, text_img("—  " + ln, "oswald", 24, (215, 210, 198), w=400), 110, 1035 + i * 38, la, "lm")


def scene5(c, t):
    """LO QUE QUEDÓ: the sixties, the open question, the title."""
    bg(c, BLACK, seed=15, alpha=ease(ramp(t, S5 - 0.1, S5 + 0.3)))
    cam = (BASE_CAM[0], BASE_CAM[1], BASE_CAM[2])
    a = ease(ramp(t, S5 - 0.1, S5 + 0.4)) * (1 - ease(ramp(t, Q + 0.2, Q + 0.9)))
    if a > 0:
        hl = [(g, 1.0, (70, 20, 18)) for g, *_ in REGION_CARDS]
        map_layer(c, cam, a, hl, dim=0.5)
        put(c, text_img("AÑOS SESENTA", "bebas", 120, PAPER, tracking=4), 70, 205, a, "lm")
        put(c, text_img("antecedentes, no causa única", "oswald", 32, RED_TXT, tracking=2, w=500), 74, 272, a, "lm")
        m1 = ease(ramp(t, ls("L13") + 0.9, ls("L13") + 1.3))
        m2 = ease(ramp(t, ls("L13") + 1.6, ls("L13") + 2.0))
        city_marker(c, *MARQUETALIA, cam, "1964 · MARQUETALIA (TOLIMA)", a * m1, size=27, side="l",
                    sub="Núcleo de las FARC (nombre adoptado en 1966)", pulse=(t * 0.8) % 1)
        city_marker(c, *SAN_VICENTE, cam, "1964 · SAN VICENTE DE CHUCURÍ", a * m2, size=27, side="l",
                    sub="Santander · nace el ELN", pulse=(t * 0.8 + 0.5) % 1)
        para(c, ["También pesaron la Revolución cubana, la Guerra Fría", "y los conflictos agrarios sin resolver."],
             70, 1110, 23, GRAY2, a * ease(ramp(t, ls("L13") + 2.2, ls("L13") + 2.6)), w=400)
    # the question: a timeline that does not close
    qa = ease(ramp(t, Q + 0.3, Q + 0.8)) * (1 - ease(ramp(t, TITLE - 0.2, TITLE + 0.2)))
    if qa > 0:
        d = ImageDraw.Draw(c)
        y = 700
        lp = ease_out(ramp(t, Q + 0.3, Q + 2.6))
        x0, x1 = 100, 860
        d.line([(x0, y), (x0 + (x1 - x0) * lp, y)], fill=GRAY2 + (int(255 * qa),), width=3)
        for fx, yr in ((0.0, "1948"), (0.3, "1958"), (0.55, "1964")):
            if lp >= fx:
                x = x0 + (x1 - x0) * fx
                d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=PAPER + (int(255 * qa),))
                put(c, text_img(yr, "bebas", 60, PAPER), x, y - 50, qa, "mm")
        if lp > 0.97:
            put(c, text_img("?", "bebas", 190, RED_TXT), x1 + 10, y - 10, qa * ease(ramp(t, Q + 2.5, Q + 2.8)), "mm")
    # title card
    ta = ease(ramp(t, TITLE, TITLE + 0.5)) * (1 - ease(ramp(t, DUR - 0.45, DUR - 0.02)))
    if ta > 0:
        put(c, text_img("COLOMBIA", "oswald", 40, GRAY2, tracking=14, w=500), W / 2, 600, ta, "mm")
        put(c, text_img("CUANDO LA VIOLENCIA", "bebas", 118, PAPER, tracking=3), W / 2, 700, ta, "mm")
        put(c, text_img("SE VOLVIÓ COTIDIANA", "bebas", 118, RED_TXT, tracking=3), W / 2, 805, ta, "mm")
        d = ImageDraw.Draw(c)
        rr = ease_out(ramp(t, TITLE + 0.2, TITLE + 0.9))
        d.rectangle([W / 2 - 300 * rr, 880, W / 2 + 300 * rr, 885], fill=RED + (int(255 * ta),))
        put(c, text_img("Fuentes en la descripción", "oswald", 24, GRAY2, w=400), W / 2, 930, ta * 0.9, "mm")


def frame(fi):
    t = fi / FPS
    c = Image.new("RGBA", (W, H), BLACK + (255,))
    if t < S2 + 0.6:
        scene1(c, t)
    if S2 <= t < S3 + 0.7:
        scene2(c, t)
    if S3 - 0.1 <= t < S4 + 0.45:
        scene3(c, t)
    if S4 - 0.1 <= t < S5 + 0.3:
        scene4(c, t)
    if t >= S5 - 0.1:
        scene5(c, t)
    c.alpha_composite(sub_band())
    draw_subs(c, t)
    return finish(c, t, fi)


def render_range(args):
    fi = args
    return frame(fi).tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=float, nargs="*", help="write PNG stills at these seconds")
    ap.add_argument("--frames", type=int, help="render only the first N frames")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--audio", default=str(OUT / "mezcla_sin_voz.wav"))
    a = ap.parse_args()
    if a.preview is not None:
        pdir = OUT / "preview"
        pdir.mkdir(parents=True, exist_ok=True)
        for s in a.preview:
            Image.fromarray(frame(int(round(s * FPS)))).save(pdir / f"f_{s:05.2f}.png")
        return
    n = a.frames or int(round(DUR * FPS))
    dst = OUT / "la_violencia_tiktok_1080x1920.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if Path(a.audio).exists():
        cmd += ["-i", a.audio, "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest"]
    cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-maxrate", "16M", "-bufsize", "32M",
            "-profile:v", "high", "-level", "4.2", "-g", "60",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-movflags", "+faststart", "-metadata", "title=Colombia: cuando la violencia se volvió cotidiana",
            str(dst)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(a.workers) as pool:
        for i, buf in enumerate(pool.imap(render_range, range(n), chunksize=6)):
            proc.stdin.write(buf)
            if i % 60 == 0:
                print(f"frame {i}/{n}", file=sys.stderr, flush=True)
    proc.stdin.close()
    sys.exit(proc.wait())


if __name__ == "__main__":
    main()
