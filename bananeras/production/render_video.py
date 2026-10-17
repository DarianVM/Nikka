#!/usr/bin/env python3
"""Render *La Masacre de las Bananeras* — 1080x1920, 30 fps, H.264/AAC.

Every image is drawn here (Pillow + NumPy): maps from coordinates, figures, buildings,
documents and typography. No photographs are used and none are imitated.

Reads production/timeline.json and out/narration_timing.json (written by build_audio.py),
muxes out/mix.wav and writes out/bananeras_1080x1920.mp4 (+ out/subtitles.srt).

  python3 render_video.py                 full render
  python3 render_video.py --frames 3,15   write PNG stills to out/preview/ instead
"""
import argparse
import json
import math
import os
import re
import subprocess
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
FONTS = ROOT / "assets" / "fonts"
W, H = 1080, 1920
FPS = 30

# palette
LEAF = (30, 56, 38)
LEAF2 = (58, 96, 56)
LEAF3 = (96, 132, 74)
PAPER = (228, 216, 188)
PAPER2 = (204, 188, 152)
CHAR = (22, 20, 18)
INK = (34, 30, 26)
GOLD = (196, 156, 78)
RED = (150, 30, 26)
NIGHT = (14, 18, 24)
CREAM = (236, 228, 210)

SAFE_X0, SAFE_X1 = 90, 960   # right margin leaves room for the platform buttons
CX = (SAFE_X0 + SAFE_X1) / 2
SUB_Y = 1372                 # subtitles sit above the caption area


# ---------------------------------------------------------------- easing / util
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in(x):
    x = clamp(x)
    return x ** 3


def ramp(t, t0, t1):
    return ease((t - t0) / max(t1 - t0, 1e-6))


def window(t, t0, t1, fin=0.35, fout=0.35):
    return min(ramp(t, t0, t0 + fin), 1 - ramp(t, t1 - fout, t1))


def lerp(a, b, k):
    return a + (b - a) * k


def mix(c1, c2, k):
    return tuple(int(lerp(a, b, k)) for a, b in zip(c1, c2))


@lru_cache(None)
def font(name, size, var=None):
    f = ImageFont.truetype(str(FONTS / name), size)
    if var:
        f.set_variation_by_name(var)
    return f


FACES = {
    "serif": lambda s: font("PlayfairDisplay[wght].ttf", s, "Black"),
    "serifb": lambda s: font("PlayfairDisplay[wght].ttf", s, "Bold"),
    "italic": lambda s: font("PlayfairDisplay-Italic[wght].ttf", s, "Bold Italic"),
    "sans": lambda s: font("Oswald[wght].ttf", s, "SemiBold"),
    "sansl": lambda s: font("Oswald[wght].ttf", s, "Regular"),
    "bebas": lambda s: font("BebasNeue-Regular.ttf", s),
    "old": lambda s: font("OldStandard-Bold.ttf", s),
    "oldr": lambda s: font("OldStandard-Regular.ttf", s),
    "type": lambda s: font("SpecialElite-Regular.ttf", s),
}


@lru_cache(None)
def text_img(text, face, size, fill, tracking=0, stroke=0, stroke_fill=(0, 0, 0)):
    f = FACES[face](size)
    asc, desc = f.getmetrics()
    if tracking:
        widths = [f.getlength(c) for c in text]
        total = int(sum(widths) + tracking * (len(text) - 1)) + 2 * stroke + 10
        im = Image.new("RGBA", (total, asc + desc + 2 * stroke + 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x = stroke + 5
        for c, w in zip(text, widths):
            d.text((x, stroke + 5), c, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
            x += w + tracking
        return im
    w = int(f.getlength(text)) + 2 * stroke + 10
    im = Image.new("RGBA", (w, asc + desc + 2 * stroke + 10), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((stroke + 5, stroke + 5), text, font=f, fill=fill,
                            stroke_width=stroke, stroke_fill=stroke_fill)
    return im


def with_alpha(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def put(canvas, im, cx, cy, scale=1.0, alpha=1.0, rot=0.0):
    """Composite RGBA `im` centred at (cx, cy), cropped safely at the canvas edges."""
    if alpha <= 0.003 or im is None:
        return
    if abs(scale - 1) > 1e-3:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    if rot:
        im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
    im = with_alpha(im, alpha)
    x, y = int(round(cx - im.width / 2)), int(round(cy - im.height / 2))
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + im.width, canvas.width), min(y + im.height, canvas.height)
    if x1 <= x0 or y1 <= y0:
        return
    canvas.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def overlay(canvas, color, a):
    if a <= 0.003:
        return
    canvas.alpha_composite(Image.new("RGBA", canvas.size, (*color[:3], int(255 * clamp(a)))))


def layer(fn, size=(W, H), ss=1):
    """Draw with ImageDraw on a transparent layer (optionally supersampled) and return it."""
    lay = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
    fn(ImageDraw.Draw(lay), ss)
    if ss > 1:
        lay = lay.resize(size, Image.LANCZOS)
    return lay


def title(canvas, text, y, size=96, face="serif", fill=CREAM, alpha=1.0, tracking=0, rise=0.0, shadow=True):
    im = text_img(text, face, size, fill, tracking)
    if im.width > SAFE_X1 - SAFE_X0:
        im = im.resize((SAFE_X1 - SAFE_X0, int(im.height * (SAFE_X1 - SAFE_X0) / im.width)), Image.LANCZOS)
    if shadow:
        sh = text_img(text, face, size, (0, 0, 0), tracking)
        if sh.size != im.size:
            sh = sh.resize(im.size, Image.LANCZOS)
        put(canvas, sh.filter(ImageFilter.GaussianBlur(6)), CX + 3, y + 5 + rise, alpha=alpha * 0.7)
    put(canvas, im, CX, y + rise, alpha=alpha)


# ---------------------------------------------------------------- textures
def noise_field(w, h, scale, seed):
    r = np.random.default_rng(seed)
    small = r.random((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def paper_texture(color, seed=1, stains=True, w=W, h=H, amt=20):
    base = np.ones((h, w, 3), np.float32) * np.array(color, np.float32)
    n = noise_field(w, h, 6, seed) * 0.5 + noise_field(w, h, 60, seed + 1) * 0.5
    fib = noise_field(w, h, 2, seed + 2)
    base += ((n - 0.5) * amt + (fib - 0.5) * amt * 0.5)[..., None]
    if stains:
        st = np.clip(noise_field(w, h, 160, seed + 3) - 0.6, 0, 1) * 80
        base -= st[..., None] * np.array([0.5, 0.75, 1.0])
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")


def tinted(img, color, k):
    """Multiply-ish tint of an RGBA image toward `color` by k."""
    a = np.asarray(img, np.float32)
    a[..., :3] = a[..., :3] * (1 - k) + a[..., :3] * np.array(color, np.float32) / 255 * k
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


INK_NOISE = None


def ink_reveal(im, progress):
    """Reveal an RGBA layer through an organic ink-bleed mask."""
    global INK_NOISE
    if progress >= 0.999:
        return im
    if progress <= 0.001:
        return None
    if INK_NOISE is None:
        INK_NOISE = noise_field(W, H, 40, 77) * 0.6 + noise_field(W, H, 8, 78) * 0.4
    n = Image.fromarray((INK_NOISE * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR)
    n = np.asarray(n, np.float32) / 255
    yy, xx = np.mgrid[0:im.height, 0:im.width]
    radial = np.hypot((xx - im.width / 2) / im.width, (yy - im.height / 2) / im.height)
    m = np.clip((progress * 1.25 - (radial * 0.9 + n * 0.55)) * 14, 0, 1)
    out = im.copy()
    out.putalpha(Image.fromarray((np.asarray(im.getchannel("A"), np.float32) * m).astype(np.uint8)))
    return out


# ---------------------------------------------------------------- geography
# Simplified outline of Colombia (lon, lat), clockwise from La Guajira. Stylized, not survey-grade.
COLOMBIA = [
    (-71.7, 12.45), (-72.3, 11.85), (-72.9, 11.55), (-73.6, 11.3), (-74.2, 11.27), (-74.28, 11.0),
    (-74.85, 11.05), (-75.3, 10.75), (-75.55, 10.4), (-75.7, 9.9), (-75.9, 9.45), (-76.2, 9.0),
    (-76.8, 8.6), (-77.35, 8.65), (-77.8, 7.6), (-77.9, 7.2), (-77.5, 6.6), (-77.4, 5.6),
    (-77.3, 4.2), (-77.5, 3.3), (-78.1, 2.6), (-78.8, 1.8), (-78.85, 1.4), (-77.4, 0.8),
    (-76.5, 0.3), (-75.3, -0.1), (-74.4, -0.7), (-73.6, -1.3), (-72.9, -2.4), (-71.9, -2.2),
    (-70.6, -3.6), (-69.95, -4.2), (-69.4, -1.1), (-70.0, 0.6), (-69.4, 1.1), (-67.9, 1.8),
    (-67.3, 1.9), (-67.6, 3.4), (-67.8, 4.6), (-67.5, 6.2), (-68.6, 6.1), (-69.4, 6.1),
    (-70.1, 6.95), (-71.0, 7.0), (-72.0, 7.3), (-72.45, 7.9), (-72.4, 8.4), (-72.8, 9.1),
    (-73.0, 9.7), (-72.9, 10.4), (-72.5, 11.1), (-71.9, 11.6), (-71.3, 11.85), (-71.15, 12.2),
]
MAGDALENA_RIVER = [(-76.3, 1.9), (-75.6, 2.6), (-75.3, 3.0), (-74.9, 4.3), (-74.75, 5.2), (-74.4, 6.5),
                   (-73.85, 7.06), (-74.0, 8.2), (-74.4, 9.2), (-74.6, 10.0), (-74.8, 10.9)]
CIENAGA_GRANDE = [(-74.52, 10.99), (-74.42, 10.98), (-74.33, 10.95), (-74.29, 10.88), (-74.28, 10.8), (-74.31, 10.72),
                  (-74.36, 10.66), (-74.44, 10.63), (-74.52, 10.66), (-74.57, 10.73), (-74.6, 10.82), (-74.58, 10.92)]
RAIL = [(-74.2, 11.24), (-74.25, 11.0), (-74.22, 10.9), (-74.18, 10.8), (-74.16, 10.72), (-74.19, 10.59), (-74.19, 10.52)]
TOWNS = {"Santa Marta": (-74.2, 11.24), "Ciénaga": (-74.25, 11.0), "Sevilla": (-74.18, 10.79),
         "Aracataca": (-74.19, 10.59), "Fundación": (-74.19, 10.52)}
STRIKE_TOWNS = [(-74.25, 11.0), (-74.22, 10.92), (-74.2, 10.86), (-74.18, 10.8), (-74.16, 10.72),
                (-74.19, 10.59), (-74.19, 10.52), (-74.12, 10.66), (-74.1, 10.85)]
CITIES = {"Bogotá": (-74.07, 4.71), "Medellín": (-75.57, 6.25), "Cali": (-76.53, 3.45),
          "Barranquilla": (-74.8, 10.96), "Bucaramanga": (-73.12, 7.12), "Cartagena": (-75.51, 10.4),
          "Pasto": (-77.28, 1.21), "Neiva": (-75.28, 2.93)}


class Cam:
    def __init__(self, lon, lat, k, cx=W / 2, cy=H * 0.46):
        self.lon, self.lat, self.k, self.cx, self.cy = lon, lat, k, cx, cy

    def __call__(self, lon, lat):
        return (self.cx + (lon - self.lon) * self.k, self.cy - (lat - self.lat) * self.k * 1.01)


def resample_poly(pts, n):
    pts = np.array(pts + [pts[0]], np.float64)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    s = np.linspace(0, cum[-1], n, endpoint=False)
    return np.column_stack([np.interp(s, cum, pts[:, 0]), np.interp(s, cum, pts[:, 1])])


def leaf_outline(n, cx, cy, length, width, angle=-0.35):
    """Banana-leaf outline (two arcs around a midrib) resampled to n points, in pixels."""
    t = np.linspace(0, 1, n // 2)
    half = width * (np.sin(np.pi * t) ** 0.8) * (1 - 0.25 * t)
    xs = (t - 0.5) * length
    top = np.column_stack([xs, -half])
    bot = np.column_stack([xs[::-1], half[::-1] * 0.92])
    p = np.vstack([top, bot])
    c, s = math.cos(angle), math.sin(angle)
    p = p @ np.array([[c, s], [-s, c]])
    return p + np.array([cx, cy])


# ---------------------------------------------------------------- figures (drawn at supersampled scale)
SKINS = [(92, 60, 40), (120, 80, 52), (70, 46, 32), (140, 96, 64), (104, 70, 46)]
SHIRTS = [(214, 204, 182), (196, 186, 160), (222, 214, 196), (176, 166, 140)]
TROUSERS = [(92, 84, 66), (70, 66, 56), (120, 108, 84), (60, 58, 52)]


def draw_person(d, x, y, h, kind="worker", seed=0, sil=None, step=0.0):
    """A dignified, simplified 1920s figure. Feet at (x, y), height h.
    kind: worker | carry | paper | woman | soldier.  sil: single colour (silhouette) or None."""
    r = np.random.default_rng(seed)
    skin = sil or SKINS[seed % len(SKINS)]
    shirt = sil or SHIRTS[(seed // 2) % len(SHIRTS)]
    trous = sil or TROUSERS[(seed // 3) % len(TROUSERS)]
    hatc = sil or (196, 168, 104)
    if kind == "soldier":
        shirt = trous = sil or (52, 60, 54)
        hatc = sil or (40, 46, 42)
    lean = r.uniform(-0.015, 0.015) * h
    head_r = h * 0.062
    hx, hy = x + lean, y - h * 0.865
    sh_y, waist_y = y - h * 0.77, y - h * 0.47
    sw, ww = h * 0.125, h * 0.09
    stride = h * (0.05 + 0.04 * math.sin(step)) if kind != "woman" else 0
    # legs / skirt
    if kind == "woman":
        d.polygon([(x - ww * 0.9, waist_y), (x + ww * 0.9, waist_y), (x + h * 0.16, y - h * 0.03),
                   (x - h * 0.16, y - h * 0.03)], fill=sil or (120, 52, 44) if seed % 2 else sil or (60, 72, 90))
        d.rectangle((x - h * 0.06, y - h * 0.04, x - h * 0.02, y), fill=skin)
        d.rectangle((x + h * 0.02, y - h * 0.04, x + h * 0.06, y), fill=skin)
    else:
        for side in (-1, 1):
            fx = x + side * stride
            d.polygon([(x + side * ww * 0.15, waist_y), (x + side * ww, waist_y),
                       (fx + side * h * 0.04, y - h * 0.01), (fx - side * h * 0.0, y - h * 0.01)], fill=trous)
            d.ellipse((fx - h * 0.035, y - h * 0.025, fx + h * 0.05, y + h * 0.005),
                      fill=sil or ((30, 26, 22) if kind == "soldier" else skin))
        if kind == "soldier":  # leggings
            for side in (-1, 1):
                fx = x + side * stride
                d.polygon([(fx - h * 0.03 + side * h * 0.01, y - h * 0.2), (fx + h * 0.045, y - h * 0.2),
                           (fx + h * 0.045, y - h * 0.02), (fx - h * 0.025, y - h * 0.02)], fill=sil or (36, 40, 36))
    # torso
    d.polygon([(x - sw + lean, sh_y), (x + sw + lean, sh_y), (x + ww, waist_y + h * 0.03), (x - ww, waist_y + h * 0.03)],
              fill=shirt)
    if kind == "soldier":
        d.line((x - sw * 0.8 + lean, sh_y + h * 0.02, x + ww, waist_y), fill=sil or (90, 76, 50), width=max(1, int(h * 0.018)))
        d.rectangle((x - ww, waist_y - h * 0.005, x + ww, waist_y + h * 0.02), fill=sil or (80, 66, 44))
    if kind == "woman":  # shawl
        d.polygon([(x - sw * 1.1 + lean, sh_y + h * 0.01), (x + sw * 1.1 + lean, sh_y + h * 0.01),
                   (x + lean, sh_y + h * 0.2)], fill=sil or (150, 120, 90))
    # neck + head
    d.rectangle((hx - h * 0.025, hy + head_r * 0.6, hx + h * 0.025, sh_y + 2), fill=skin)
    d.ellipse((hx - head_r, hy - head_r, hx + head_r, hy + head_r), fill=skin)
    # arms
    aw = max(2, int(h * 0.052))
    lx, rx = x - sw * 0.92 + lean, x + sw * 0.92 + lean
    if kind == "carry":  # banana bunch on the shoulder, steadied with one hand
        bx, by = rx + h * 0.02, sh_y - h * 0.07
        d.line((rx, sh_y + h * 0.02, rx + h * 0.07, sh_y - h * 0.08), fill=shirt, width=aw)
        d.line((lx, sh_y + h * 0.02, lx - h * 0.02, waist_y + h * 0.04), fill=shirt, width=aw)
        bunch(d, bx, by, h * 0.16, sil)
    elif kind == "paper":
        d.line((rx, sh_y + h * 0.02, rx + h * 0.1, sh_y + h * 0.16), fill=shirt, width=aw)
        d.line((lx, sh_y + h * 0.02, lx - h * 0.02, waist_y + h * 0.04), fill=shirt, width=aw)
        px, py = rx + h * 0.1, sh_y + h * 0.1
        d.rectangle((px - h * 0.01, py - h * 0.07, px + h * 0.07, py + h * 0.03), fill=sil or (240, 234, 220))
    elif kind == "soldier":  # rifle carried at the shoulder, muzzle up
        d.line((lx, sh_y + h * 0.02, lx - h * 0.015, waist_y + h * 0.03), fill=shirt, width=aw)
        d.line((rx, sh_y + h * 0.02, rx + h * 0.03, sh_y + h * 0.18), fill=shirt, width=aw)
        d.line((rx + h * 0.05, sh_y + h * 0.26, rx + h * 0.0, sh_y - h * 0.24), fill=sil or (28, 24, 20), width=max(2, int(h * 0.022)))
    else:
        d.line((lx, sh_y + h * 0.02, lx - h * 0.02, waist_y + h * 0.04), fill=shirt, width=aw)
        d.line((rx, sh_y + h * 0.02, rx + h * 0.02, waist_y + h * 0.04), fill=shirt, width=aw)
    # headwear
    if kind == "soldier":  # kepi with visor
        d.rectangle((hx - head_r * 0.95, hy - head_r * 1.7, hx + head_r * 0.85, hy - head_r * 0.35), fill=hatc)
        d.polygon([(hx + head_r * 0.2, hy - head_r * 0.45), (hx + head_r * 1.5, hy - head_r * 0.25),
                   (hx + head_r * 0.2, hy - head_r * 0.2)], fill=sil or (20, 20, 18))
    elif kind == "woman":
        d.chord((hx - head_r * 1.1, hy - head_r * 1.2, hx + head_r * 1.1, hy + head_r * 0.6), 180, 360, fill=sil or (210, 200, 180))
    else:  # straw hat
        d.ellipse((hx - head_r * 2.1, hy - head_r * 0.85, hx + head_r * 2.1, hy - head_r * 0.25), fill=hatc)
        d.rounded_rectangle((hx - head_r * 1.0, hy - head_r * 1.75, hx + head_r * 1.0, hy - head_r * 0.45),
                            radius=head_r * 0.4, fill=hatc)
        if not sil:
            d.rectangle((hx - head_r * 1.0, hy - head_r * 0.75, hx + head_r * 1.0, hy - head_r * 0.55), fill=(90, 60, 40))


def bunch(d, x, y, s, sil=None):
    """Hanging banana bunch: stalk plus rows of fingers."""
    d.line((x, y - s * 0.6, x, y + s * 0.5), fill=sil or (70, 90, 50), width=max(2, int(s * 0.08)))
    for row in range(5):
        ry = y - s * 0.4 + row * s * 0.2
        rw = s * (0.42 - 0.04 * abs(row - 2))
        for k in range(-2, 3):
            fx = x + k * rw * 0.42
            d.chord((fx - s * 0.12, ry - s * 0.07, fx + s * 0.12, ry + s * 0.13), 0, 180,
                    fill=sil or (LEAF3 if (row + k) % 2 else (120, 150, 70)))


def banana_plant(d, x, y, h, seed, col=None, ss=1):
    """Banana plant: tapered pseudostem, arching torn leaves, one hanging bunch."""
    r = np.random.default_rng(seed)
    stem = col or (82, 100, 60)
    d.polygon([(x - h * 0.05, y), (x + h * 0.05, y), (x + h * 0.03, y - h * 0.62), (x - h * 0.03, y - h * 0.62)], fill=stem)
    top = (x, y - h * 0.6)
    n = 7
    for i in range(n):
        a = -math.pi / 2 + (i - (n - 1) / 2) * 0.42 + r.uniform(-0.12, 0.12)
        L = h * r.uniform(0.42, 0.6)
        droop = r.uniform(0.25, 0.5)
        pts_up, pts_dn = [], []
        for k in range(14):
            u = k / 13
            ang = a + droop * u * u * (1 if math.cos(a) >= 0 else -1) * 1.6
            px = top[0] + math.cos(a) * L * u + (math.cos(ang) - math.cos(a)) * L * u * 0.5
            py = top[1] + math.sin(a) * L * u + (math.sin(ang) - math.sin(a)) * L * u * 0.5 + droop * L * u * u * 0.9
            wdt = h * 0.075 * math.sin(math.pi * min(1, u * 1.05)) ** 0.7
            nx, ny = -math.sin(a), math.cos(a)
            pts_up.append((px + nx * wdt, py + ny * wdt))
            pts_dn.append((px - nx * wdt, py - ny * wdt))
        c = col or (LEAF2 if i % 2 else LEAF3 if i % 3 == 0 else (70, 110, 62))
        d.polygon(pts_up + pts_dn[::-1], fill=c)
        if not col:  # midrib + a couple of tears
            d.line(pts_up[0:1] + [((pu[0] + pd[0]) / 2, (pu[1] + pd[1]) / 2) for pu, pd in zip(pts_up, pts_dn)],
                   fill=(150, 170, 110), width=max(1, int(h * 0.006)))
    if h > 60:
        bunch(d, x + h * 0.06, y - h * 0.46, h * 0.16, col)


# ---------------------------------------------------------------- props
def train_layer(cars=6, h=110, sil=None):
    """Steam locomotive pulling flat cars piled with banana bunches. Returns RGBA facing left."""
    ss = 3
    cw = int(h * 2.0)
    Wt = int(h * 2.4 + cars * (cw + h * 0.12)) + 20
    Ht = int(h * 1.6)

    def fn(d, s):
        k = s
        base = Ht * k - 10 * k
        dark = sil or (30, 28, 26)
        gold = sil or (150, 120, 60)
        # locomotive (left)
        lx = 10 * k
        d.rounded_rectangle((lx + h * 0.35 * k, base - h * 0.95 * k, lx + h * 1.6 * k, base - h * 0.35 * k), radius=h * 0.25 * k, fill=dark)
        d.rectangle((lx + h * 1.45 * k, base - h * 1.25 * k, lx + h * 2.2 * k, base - h * 0.35 * k), fill=dark)
        d.rectangle((lx + h * 1.55 * k, base - h * 1.15 * k, lx + h * 1.85 * k, base - h * 0.85 * k), fill=sil or (210, 170, 90))
        d.rectangle((lx + h * 1.4 * k, base - h * 1.32 * k, lx + h * 2.3 * k, base - h * 1.22 * k), fill=dark)
        d.polygon([(lx + h * 0.55 * k, base - h * 0.95 * k), (lx + h * 0.75 * k, base - h * 0.95 * k),
                   (lx + h * 0.82 * k, base - h * 1.4 * k), (lx + h * 0.48 * k, base - h * 1.4 * k)], fill=dark)
        d.polygon([(lx + h * 0.05 * k, base - h * 0.15 * k), (lx + h * 0.4 * k, base - h * 0.5 * k),
                   (lx + h * 0.4 * k, base - h * 0.15 * k)], fill=dark)
        d.line((lx + h * 0.4 * k, base - h * 0.62 * k, lx + h * 1.5 * k, base - h * 0.62 * k), fill=gold, width=int(2 * k))
        for wx in (0.6, 1.0, 1.4, 1.95):
            r_ = h * (0.2 if wx < 1.8 else 0.16) * k
            cxw = lx + h * wx * k
            d.ellipse((cxw - r_, base - h * 0.05 * k - 2 * r_, cxw + r_, base - h * 0.05 * k), fill=dark, outline=gold, width=int(2 * k))
        # cars
        x0 = lx + h * 2.4 * k
        for c in range(cars):
            cx0 = x0 + c * (cw + h * 0.12) * k
            d.rectangle((cx0, base - h * 0.42 * k, cx0 + cw * k, base - h * 0.22 * k), fill=dark)
            d.line((cx0 - h * 0.12 * k, base - h * 0.3 * k, cx0, base - h * 0.3 * k), fill=dark, width=int(3 * k))
            for wx in (0.18, 0.4, 0.6, 0.82):
                r_ = h * 0.11 * k
                cxw = cx0 + cw * wx * k
                d.ellipse((cxw - r_, base - h * 0.05 * k - 2 * r_, cxw + r_, base - h * 0.05 * k), fill=dark)
            # stakes + bunches piled high
            for sx in np.linspace(0.04, 0.96, 6):
                d.line((cx0 + cw * sx * k, base - h * 0.42 * k, cx0 + cw * sx * k, base - h * 0.95 * k), fill=dark, width=int(3 * k))
            rr = np.random.default_rng(c)
            for row in range(3):
                for b in range(5):
                    bx = cx0 + cw * k * (0.12 + b * 0.19 + rr.uniform(-0.03, 0.03))
                    by = base - h * (0.55 + row * 0.18) * k
                    bunch(d, bx, by, h * 0.22 * k, sil)
    return layer(fn, (Wt, Ht), ss)


def station_layer(w=1080, h=520, col=(8, 10, 14), lit=(232, 190, 110)):
    """A 1920s Caribbean railway station and houses, seen at night (silhouette with lit windows)."""
    def fn(d, s):
        k = s
        g = h * k
        # houses left/right with balconies
        for hx0, hw, hh in ((0, 300, 300), (780, 300, 330)):
            d.rectangle((hx0 * k, g - hh * k, (hx0 + hw) * k, g), fill=col)
            d.polygon([(hx0 * k - 10 * k, g - hh * k), ((hx0 + hw) * k + 10 * k, g - hh * k),
                       ((hx0 + hw / 2) * k, g - (hh + 60) * k)], fill=col)
            for wx in range(3):
                x = (hx0 + 40 + wx * 90) * k
                d.rectangle((x, g - (hh - 60) * k, x + 40 * k, g - (hh - 140) * k), fill=lit if (wx + hx0) % 3 else (60, 50, 40))
        # station: long low building, hipped tin roof, veranda posts, sign
        sx0, sx1 = 250 * k, 830 * k
        d.rectangle((sx0, g - 230 * k, sx1, g), fill=col)
        d.polygon([(sx0 - 50 * k, g - 230 * k), (sx1 + 50 * k, g - 230 * k), (sx1 - 40 * k, g - 330 * k), (sx0 + 40 * k, g - 330 * k)], fill=col)
        for px in np.linspace(sx0 - 30 * k, sx1 + 30 * k, 9):
            d.rectangle((px - 5 * k, g - 230 * k, px + 5 * k, g), fill=col)
        for i, wx in enumerate(np.linspace(sx0 + 60 * k, sx1 - 100 * k, 5)):
            d.rectangle((wx, g - 180 * k, wx + 46 * k, g - 70 * k), fill=lit if i != 2 else (70, 56, 40))
        d.rectangle((470 * k, g - 300 * k, 610 * k, g - 262 * k), fill=(40, 34, 28))
        f = FACES["old"](int(26 * k))
        d.text((540 * k, g - 281 * k), "ESTACIÓN", font=f, fill=(200, 170, 110), anchor="mm")
    return layer(fn, (w, h), 2)


def machete_hat_layer(w=520, h=260):
    def fn(d, s):
        k = s
        # machete lying diagonally
        d.polygon([(40 * k, 190 * k), (330 * k, 120 * k), (360 * k, 128 * k), (350 * k, 150 * k), (60 * k, 210 * k)], fill=(150, 150, 140))
        d.line((60 * k, 205 * k, 345 * k, 140 * k), fill=(110, 110, 104), width=int(2 * k))
        d.rounded_rectangle((330 * k, 118 * k, 430 * k, 150 * k), radius=10 * k, fill=(70, 46, 30))
        # straw hat
        d.ellipse((250 * k, 170 * k, 500 * k, 245 * k), fill=(176, 148, 90))
        d.chord((310 * k, 120 * k, 440 * k, 240 * k), 180, 360, fill=(190, 160, 100))
        d.rectangle((312 * k, 170 * k, 438 * k, 186 * k), fill=(90, 60, 40))
    return layer(fn, (w, h), 3)


def vale_layer(w=330, h=190):
    """A company-store scrip voucher ('vale'), generic design, no real company mark."""
    im = paper_texture((214, 200, 160), seed=41, stains=False, w=w, h=h, amt=14)

    def fn(d, s):
        d.rectangle((8, 8, w - 9, h - 9), outline=(110, 40, 34), width=3)
        d.rectangle((16, 16, w - 17, h - 17), outline=(110, 40, 34), width=1)
        d.text((w / 2, 52), "VALE", font=FACES["old"](48), fill=(110, 40, 34), anchor="mm")
        d.text((w / 2, 100), "COMISARIATO", font=FACES["sans"](26), fill=(60, 50, 40), anchor="mm")
        d.text((w / 2, 140), "canjeable sólo en la tienda", font=FACES["oldr"](20), fill=(60, 50, 40), anchor="mm")
    im.alpha_composite(layer(fn, (w, h)))
    return im


def document_layer(w=780, h=980):
    """Workers' petition (pliego): typewritten demands drawn line by line by the scene."""
    im = paper_texture(PAPER, seed=31, w=w, h=h, amt=16)
    m = Image.new("L", (w, h), 0)
    r = np.random.default_rng(3)
    pts = [(x, r.uniform(0, 8)) for x in np.linspace(0, w, 30)] + [(w - r.uniform(0, 8), y) for y in np.linspace(0, h, 40)] + \
          [(x, h - r.uniform(0, 8)) for x in np.linspace(w, 0, 30)] + [(r.uniform(0, 8), y) for y in np.linspace(h, 0, 40)]
    ImageDraw.Draw(m).polygon(pts, fill=255)
    im.putalpha(m)
    return im


DEMANDS = ["Seguro colectivo obligatorio", "Descanso dominical pagado", "Pago en dinero, no en vales",
           "Fin del sistema de contratistas", "Aumento de salarios", "Vivienda y hospitales dignos"]


def newspaper_layer(w=860, h=1100, seed=5, headline=None):
    """Generic newsprint page (no real masthead): headline space, columns of greeked text."""
    im = paper_texture((222, 212, 190), seed=seed, w=w, h=h, amt=18)

    def fn(d, s):
        r = np.random.default_rng(seed)
        d.line((40, 40, w - 40, 40), fill=INK, width=3)
        d.line((40, 150, w - 40, 150), fill=INK, width=2)
        d.text((w / 2, 96), "EDICIÓN EXTRAORDINARIA", font=FACES["old"](46), fill=INK, anchor="mm")
        y0 = 180
        if headline:
            for i, ln in enumerate(headline):
                d.text((w / 2, y0 + 50 + i * 86), ln, font=FACES["serif"](78), fill=INK, anchor="mm")
            y0 += 70 + 86 * len(headline)
        cols = 4
        cw = (w - 80 - 30 * (cols - 1)) / cols
        for c in range(cols):
            x = 40 + c * (cw + 30)
            y = y0 + 10
            while y < h - 60:
                if r.random() < 0.06:
                    y += 22
                    continue
                L = cw * (r.uniform(0.6, 1.0) if r.random() < 0.15 else 1.0)
                d.line((x, y, x + L, y), fill=(70, 64, 56), width=5)
                y += 15
    im.alpha_composite(layer(fn, (w, h)))
    return im


def gaitan_portrait(size=620):
    """Original illustrated portrait of Jorge Eliécer Gaitán (late 1920s): profile facing right,
    slicked-back dark hair, strong jaw, clean-shaven, suit and tie — in an engraved oval medallion."""
    S = 1000

    def fn(d, s):
        k = s * size / S
        P = lambda pts: [(x * k, y * k) for x, y in pts]
        d.ellipse(P([(40, 40), (960, 960)]), fill=(26, 34, 30))
        d.ellipse(P([(60, 60), (940, 940)]), outline=(196, 156, 78), width=int(6 * k))
        d.ellipse(P([(84, 84), (916, 916)]), outline=(196, 156, 78), width=int(2 * k))
        skin = (176, 132, 96)
        dark = (16, 14, 12)
        # jacket + shoulders
        d.polygon(P([(170, 910), (230, 690), (380, 620), (520, 630), (640, 630), (760, 690), (830, 910)]), fill=(40, 40, 46))
        # shirt collar + tie
        d.polygon(P([(500, 630), (600, 620), (640, 690), (560, 790), (480, 690)]), fill=(232, 226, 210))
        d.polygon(P([(545, 660), (585, 660), (600, 830), (565, 890), (530, 830)]), fill=(120, 30, 28))
        # lapels
        d.polygon(P([(470, 650), (540, 830), (430, 910), (380, 690)]), fill=(30, 30, 36))
        d.polygon(P([(640, 650), (590, 830), (690, 910), (740, 710)]), fill=(30, 30, 36))
        # neck
        d.polygon(P([(468, 500), (610, 540), (615, 650), (470, 660)]), fill=(150, 108, 78))
        # head profile (facing right)
        head = [(330, 330), (360, 230), (440, 170), (540, 150), (620, 175), (660, 230), (672, 290),
                (688, 330), (720, 395), (712, 410), (684, 418), (690, 440), (680, 452), (688, 474),
                (676, 500), (672, 532), (648, 556), (600, 568), (530, 560), (480, 530), (440, 500),
                (380, 470), (342, 410)]
        d.polygon(P(head), fill=skin)
        # ear
        d.ellipse(P([(450, 330), (510, 420)]), fill=(150, 108, 78))
        d.arc(P([(462, 345), (500, 410)]), 300, 120, fill=(110, 76, 56), width=int(5 * k))
        # slicked-back hair
        hair = [(320, 345), (330, 260), (380, 190), (450, 150), (540, 132), (620, 150), (668, 205),
                (660, 228), (600, 205), (530, 200), (470, 230), (430, 300), (400, 360), (360, 400)]
        d.polygon(P(hair), fill=dark)
        for i in range(5):  # comb highlights
            y = 160 + i * 18
            d.arc(P([(360 + i * 10, y), (680 - i * 6, y + 210)]), 200, 300, fill=(90, 84, 74), width=int(3 * k))
        # eye, brow, mouth line
        d.line(P([(612, 288), (650, 280)]), fill=dark, width=int(9 * k))
        d.ellipse(P([(626, 300), (646, 314)]), fill=dark)
        d.line(P([(648, 462), (684, 458)]), fill=(110, 70, 56), width=int(4 * k))
        # rim light on the face edge
        d.line(P(head[4:17]), fill=(236, 200, 140), width=int(5 * k))
    im = layer(fn, (size, size), 3)
    # engraving: fine horizontal hatching multiplied over the medallion
    hatch = np.ones((size, size), np.float32)
    hatch[::4, :] = 0.82
    a = np.asarray(im, np.float32)
    a[..., :3] *= hatch[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- finishing
class Film:
    def __init__(self):
        rng = np.random.default_rng(9)
        self.grain = [(rng.standard_normal((H // 2, W // 2)) * 7).astype(np.float32) for _ in range(6)]
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.hypot((xx - W / 2) / (W * 0.62), (yy - H / 2) / (H * 0.58))
        self.vig = np.clip(1 - (r ** 2.2) * 0.5, 0.3, 1).astype(np.float32)[..., None]

    def apply(self, img, f):
        a = np.asarray(img.convert("RGB"), np.float32)
        g = np.repeat(np.repeat(self.grain[f % 6], 2, 0), 2, 1)
        flick = 1 + 0.012 * math.sin(f * 2.1) * math.sin(f * 0.77)
        a = a * flick * self.vig + g[..., None]
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(out)
        r = np.random.default_rng(f * 7 + 1)
        for _ in range(r.integers(0, 3)):
            x, y, s = r.uniform(0, W), r.uniform(0, H), r.uniform(1, 3)
            c = int(r.choice([20, 225]))
            d.ellipse((x - s, y - s, x + s, y + s), fill=(c, c, c))
        return out


def subtitle_chunks(lines, max_chars=44):
    chunks = []
    for ln in lines:
        if ln["id"] == "L7":  # the end card itself carries these words
            continue
        if "|" in ln["sub"]:  # explicit break points chosen by the editor
            clauses = [c.strip() for c in ln["sub"].split("|")]
        else:
            clauses = [c.strip() for c in re.findall(r"[^,.;:?!]+[,.;:?!]?", ln["sub"]) if c.strip()]
        groups = []
        for cl in clauses:
            if groups and "|" not in ln["sub"] and len(groups[-1]) + 1 + len(cl) <= max_chars:
                groups[-1] += " " + cl
            elif len(cl) <= max_chars:
                groups.append(cl)
            else:  # long clause: split into balanced halves on a word boundary
                ws = cl.split()
                best = min(range(1, len(ws)), key=lambda i: abs(len(" ".join(ws[:i])) - len(" ".join(ws[i:]))))
                groups += [" ".join(ws[:best]), " ".join(ws[best:])]
        total = sum(len(g) for g in groups)
        t, dur = ln["start"], ln["end"] - ln["start"]
        for g in groups:
            d = dur * len(g) / total
            chunks.append((t, t + d, g))
            t += d
    out = []
    for i, (a, b, txt) in enumerate(chunks):
        nxt = chunks[i + 1][0] if i + 1 < len(chunks) else b + 0.5
        out.append((a, min(nxt, b + 0.5), txt))
    return out


def wrap(txt, max_chars=24):
    if len(txt) <= max_chars:
        return [txt]
    ws = txt.split()
    best = min(range(1, len(ws)), key=lambda i: max(len(" ".join(ws[:i])), len(" ".join(ws[i:]))))
    return [" ".join(ws[:best]), " ".join(ws[best:])]


@lru_cache(None)
def subtitle_img(txt):
    f = FACES["sans"](58)
    lines = wrap(txt)
    lh = 76
    wmax = int(max(f.getlength(l) for l in lines)) + 50
    im = Image.new("RGBA", (wmax + 40, lh * len(lines) + 36), (0, 0, 0, 0))
    plate = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle((6, 4, im.width - 6, im.height - 4), radius=18, fill=(8, 8, 8, 165))
    im.alpha_composite(plate.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((im.width / 2, 18 + i * lh + lh / 2 - 6), l, font=f, fill=(252, 249, 240), anchor="mm",
               stroke_width=5, stroke_fill=(8, 8, 8))
    return im


def draw_subs(canvas, t, chunks):
    for a, b, txt in chunks:
        if a - 0.05 <= t < b:
            im = subtitle_img(txt)
            assert im.width <= SAFE_X1 - SAFE_X0 + 60, txt
            k = ease_out((t - a + 0.05) / 0.15)
            put(canvas, im, CX, SUB_Y + im.height / 2 + (1 - k) * 10, alpha=k)
            return


# ---------------------------------------------------------------- scenes
class Film40:
    def __init__(self, timing):
        self.T = timing["duration"]
        self.S = timing["sections"]
        self.L = {l["id"]: l for l in timing["lines"]}
        self.subs = subtitle_chunks(timing["lines"])
        self.film = Film()
        self.bg_paper = paper_texture(PAPER, 2)
        self.bg_green = tinted(paper_texture((60, 90, 62), 3, amt=14), (255, 255, 255), 0)
        self.bg_dark = paper_texture((20, 22, 22), 4, stains=False, amt=10)
        self.doc = document_layer()
        self.vale = vale_layer()
        self.train = train_layer()
        self.train_far = train_layer(cars=8, h=60, sil=(48, 60, 46))
        self.station = station_layer()
        self.station_day = station_layer(col=(70, 72, 70), lit=(96, 92, 84))
        self.tools = machete_hat_layer()
        self.portrait = gaitan_portrait()
        self.news = newspaper_layer(headline=None)
        self.news_small = newspaper_layer(w=430, h=550, seed=8)
        self.leaf_pts = leaf_outline(240, W * 0.5, H * 0.46, 1500, 330, angle=-1.05)
        self.plants = self._plantation()
        self.crowd = self._crowd()
        self.soldiers = self._soldiers()
        self.soldiers_rim = Image.new("RGBA", self.soldiers.size, (150, 170, 190, 0))
        self.soldiers_rim.putalpha(self.soldiers.getchannel("A"))
        rng = np.random.default_rng(12)
        self.papers = [(rng.uniform(120, 960), rng.uniform(1080, 1300), rng.uniform(-40, 40), rng.uniform(0.6, 1.1))
                       for _ in range(9)]

    # ---- prebuilt layers
    def _plantation(self):
        out = []
        for depth, (y, h, n, col) in enumerate([(1000, 170, 14, (64, 92, 70)), (1120, 300, 9, None), (1290, 520, 5, None)]):
            def fn(d, s, y=y, h=h, n=n, col=col, depth=depth):
                for i in range(n):
                    x = (i + 0.5) * (W * 1.6) / n + (depth * 37 % 60)
                    banana_plant(d, x * s, y * s, h * s, seed=depth * 100 + i, col=col)
            out.append(layer(fn, (int(W * 1.6), H), 2))
        return out

    def _crowd(self):
        """Night crowd: three depth rows of workers and families, as warm-edged silhouettes."""
        rows = []
        rng = np.random.default_rng(5)
        for depth, (y, h, n, col) in enumerate([(1060, 150, 22, (26, 26, 30)), (1140, 200, 16, (18, 18, 22)), (1240, 270, 11, (10, 10, 12))]):
            people = []
            for i in range(n):
                kind = rng.choice(["worker", "worker", "paper", "woman", "worker"])
                people.append((rng.uniform(-80, W + 80), y + rng.uniform(-12, 12), h * rng.uniform(0.9, 1.08), kind, int(rng.integers(0, 999))))
            rows.append((people, col))
        return rows

    def _soldiers(self):
        def fn(d, s):
            for i in range(9):
                x = (40 + i * 66) * s
                draw_person(d, x, 380 * s, 300 * s * (1 - i * 0.012), "soldier", seed=i, sil=(10, 12, 14), step=i * 0.7)
        return layer(fn, (640, 400), 2)

    # ---- map
    def draw_map(self, cv, cam, alpha=1.0, dark=False, show_rail=0.0, zone=0.0, labels=True, outline_pts=None):
        if alpha <= 0.01:
            return
        land = (40, 50, 44) if dark else (214, 200, 166)
        edge = (196, 156, 78) if dark else INK

        def fn(d, s):
            pts = outline_pts if outline_pts is not None else [cam(*p) for p in COLOMBIA]
            pts = [(x * s, y * s) for x, y in pts]
            d.polygon(pts, fill=land)
            d.line(pts + pts[:1], fill=edge, width=int(4 * s), joint="curve")
            if outline_pts is None:
                river = [cam(*p) for p in MAGDALENA_RIVER]
                d.line([(x * s, y * s) for x, y in river], fill=(90, 120, 130) if not dark else (70, 100, 110), width=int(4 * s), joint="curve")
                cg = [cam(*p) for p in CIENAGA_GRANDE]
                d.polygon([(x * s, y * s) for x, y in cg], fill=(176, 190, 178) if not dark else (36, 52, 58), outline=(90, 120, 130), width=int(2 * s))
                if zone > 0:  # hatched banana zone
                    zx0, zy0 = cam(-74.32, 11.0)
                    zx1, zy1 = cam(-74.02, 10.48)
                    for i in range(40):
                        x = zx0 + (zx1 - zx0 + (zy1 - zy0)) * i / 40
                        d.line((x * s, zy0 * s, (x - (zy1 - zy0)) * s, zy1 * s), fill=(*LEAF2, int(200 * zone)), width=int(3 * s))
                if show_rail > 0:
                    rp = [cam(*p) for p in RAIL]
                    seg = np.hypot(*np.diff(np.array(rp), axis=0).T)
                    total, acc, path = seg.sum() * show_rail, 0, [rp[0]]
                    for (a, b), L in zip(zip(rp[:-1], rp[1:]), seg):
                        if acc + L >= total:
                            k = (total - acc) / L
                            path.append((lerp(a[0], b[0], k), lerp(a[1], b[1], k)))
                            break
                        path.append(b)
                        acc += L
                    d.line([(x * s, y * s) for x, y in path], fill=CHAR if not dark else GOLD, width=int(7 * s))
                    d.line([(x * s, y * s) for x, y in path], fill=(230, 220, 190) if not dark else NIGHT, width=int(3 * s))
        lay = layer(fn, ss=1)
        if alpha < 1:
            lay = with_alpha(lay, alpha)
        cv.alpha_composite(lay)
        if outline_pts is None and labels:
            col = INK if not dark else CREAM
            for name, (lo, la) in TOWNS.items():
                x, y = cam(lo, la)
                if -50 < x < W + 50 and -50 < y < H + 50 and cam.k > 400:
                    ImageDraw.Draw(cv).ellipse((x - 9, y - 9, x + 9, y + 9), fill=(*(RED if name == "Ciénaga" else col), int(255 * alpha)))
                    put(cv, text_img(name.upper(), "sans", 30, col, 2), x + (100 if name != "Santa Marta" else 120) + len(name) * 4, y, alpha=alpha)

    # ---- scene 1: setting
    def s_setting(self, cv, t):
        s0, s1 = self.S["setting"]
        cv.alpha_composite(self.bg_green)
        # (a) banana leaf whose outline becomes the map of Colombia
        k_morph = ramp(t, 0.55, 2.0)
        cam0 = Cam(-73.0, 4.2, 58)
        zoom = ease(clamp((t - 2.3) / 2.2))
        # log-zoom with the banana zone gliding to its final screen position
        kz = math.exp(lerp(math.log(58), math.log(1250), zoom))
        tx, ty = cam0(-74.15, 10.82)
        px, py = lerp(tx, W / 2, zoom), lerp(ty, 1000, zoom)
        cam = Cam(-74.15 - (px - W / 2) / kz, 10.82 + (py - H * 0.46) / (kz * 1.01), kz)
        if t < 4.9:
            col_pts = resample_poly([cam0(*p) for p in COLOMBIA], 240)
            # align start index so the morph doesn't twist
            leaf = self.leaf_pts
            area = lambda p: np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
            if np.sign(area(leaf)) != np.sign(area(col_pts)):
                col_pts = col_pts[::-1]
            shift = min(range(len(col_pts)), key=lambda k: np.sum(np.hypot(*(np.roll(col_pts, -k, axis=0) - leaf).T)))
            col_pts = np.roll(col_pts, -shift, axis=0)
            if k_morph < 1:
                pts = leaf * (1 - k_morph) + col_pts * k_morph
                fill = mix((70, 112, 62), (214, 200, 166), k_morph)
                edge = mix((150, 170, 110), INK, k_morph)

                def fn(d, s):
                    p = [tuple(x) for x in pts]
                    d.polygon(p, fill=fill)
                    d.line(p + p[:1], fill=edge, width=5)
                    if k_morph < 0.6:  # leaf midrib + veins dissolve into map lines
                        a = 1 - k_morph / 0.6
                        mid = (pts[0] + pts[len(pts) // 2]) / 2
                        p0, p1 = pts[0], pts[len(pts) // 2 - 1]
                        d.line((tuple(p0), tuple(p1)), fill=(*edge, int(255 * a)), width=6)
                        for i in range(1, 22):
                            u = i / 22
                            q = p0 + (p1 - p0) * u
                            j = int(u * (len(pts) // 2 - 1))
                            d.line((tuple(q), tuple(pts[j])), fill=(150, 170, 110, int(200 * a)), width=2)
                            d.line((tuple(q), tuple(pts[len(pts) - 1 - j])), fill=(150, 170, 110, int(200 * a)), width=2)
                put(cv, self.bg_paper, W / 2, H / 2, alpha=k_morph)
                cv.alpha_composite(layer(fn))
            else:
                cv.alpha_composite(self.bg_paper)
                self.draw_map(cv, cam, show_rail=ramp(t, 3.4, 4.6), zone=ramp(t, 3.6, 4.4), labels=t > 3.2)
                put(cv, text_img("MAR CARIBE", "italic", 44, (90, 110, 120)), W * 0.55, cam(-74.6, 11.6)[1], alpha=ramp(t, 2.6, 3.2) * (1 - ramp(t, 4.3, 4.8)))
                put(cv, text_img("ZONA BANANERA", "sans", 40, LEAF, 6), cam(-73.7, 10.75)[0], cam(-73.7, 10.75)[1],
                    alpha=ramp(t, 3.8, 4.3) * (1 - ramp(t, 4.6, 4.9)))
        # (b) the plantation landscape rises out of the map
        k_land = ramp(t, 4.4, 5.2)
        if k_land > 0:
            land = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sky = paper_texture((222, 206, 168), 6, stains=False) if not hasattr(self, "_sky") else self._sky
            self._sky = sky
            land.alpha_composite(sky)
            ImageDraw.Draw(land).ellipse((W * 0.62, 520, W * 0.62 + 170, 690), fill=(236, 214, 160))
            # distant sierra
            hills = layer(lambda d, s: d.polygon([(0, 1010)] + [(x, 900 - 70 * math.sin(x / 170) - 40 * math.sin(x / 61)) for x in range(0, W + 1, 20)] + [(W, 1010)], fill=(150, 150, 120)))
            land.alpha_composite(hills)
            pan = (t - 4.4) * 50
            for i, pl in enumerate(self.plants[:2]):
                put(land, pl, W * 0.8 - pan * (0.4 + 0.5 * i), H / 2)
            # far train crossing behind the second row
            put(land, self.train_far, W + 500 - (t - 4.4) * 260, 1110)
            # ground + rails
            ImageDraw.Draw(land).rectangle((0, 1240, W, H), fill=(120, 104, 70))
            put(land, self.plants[2], W * 0.8 - pan * 1.4, H / 2 + 40)
            rails = layer(lambda d, s: [d.line((0, y, W, y), fill=c, width=w_) for y, c, w_ in ((1330, (60, 52, 40), 10), (1370, (60, 52, 40), 12))] +
                          [d.rectangle((x - ((t * 220) % 70), 1322, x + 18 - ((t * 220) % 70), 1384), fill=(84, 66, 46)) for x in range(0, W + 80, 70)])
            land.alpha_composite(rails)
            # workers carrying bunches toward the rail line
            def wk(d, s):
                for i in range(5):
                    x = (120 + i * 190 + (t - 4.4) * 40) * s
                    draw_person(d, x, (1300 + (i % 2) * 18) * s, (300 + (i % 3) * 14) * s, "carry" if i % 2 == 0 else "worker", seed=i + 3, step=t * 5 + i)
            land.alpha_composite(layer(wk, ss=2))
            put(cv, land, W / 2, H / 2, alpha=k_land)
            # annotations: profit flows out, wages stay
            a = ramp(t, 5.3, 5.8)
            if a > 0:
                put(cv, text_img("RIQUEZA PARA LA EXPORTACIÓN", "sans", 44, INK, 3), CX, 470, alpha=a)
                put(cv, text_img("QUIENES COSECHAN: SIN CONTRATO DIRECTO", "sans", 36, (110, 40, 34), 2), CX, 530, alpha=ramp(t, 5.9, 6.3))
        a = window(t, 0.7, s1 - 0.15, 0.5, 0.4)
        title(cv, "COLOMBIA, 1928", 300, 112, alpha=a, tracking=4, rise=(1 - ramp(t, 0.7, 1.3)) * 20,
              fill=CREAM if t < 0.6 else INK, shadow=False)

    # ---- scene 2: the strike
    def s_strike(self, cv, t):
        k0, k1 = self.S["strike"]
        u = t - k0
        cv.alpha_composite(self.bg_dark if u > 3.0 else self.bg_paper)
        if u < 3.2:
            # railway ties become the ruled lines of the petition
            a_doc = ramp(u, 0.0, 0.5)
            put(cv, self.bg_dark, W / 2, H / 2, alpha=0.0)
            doc = self.doc.copy()
            d = ImageDraw.Draw(doc)
            d.text((390, 80), "PLIEGO DE PETICIONES", font=FACES["type"](46), fill=INK, anchor="mm")
            d.text((390, 132), "Trabajadores de la Zona Bananera · 1928", font=FACES["type"](26), fill=(80, 70, 60), anchor="mm")
            for i, dem in enumerate(DEMANDS):
                y = 220 + i * 112
                d.line((60, y + 46, 720, y + 46), fill=(170, 160, 140), width=2)
                n = int(len(dem) * clamp((u - 0.4 - i * 0.32) / 0.45))
                if n > 0:
                    d.text((70, y), f"{i + 1}. " + dem[:n], font=FACES["type"](36), fill=INK)
            put(cv, doc, CX + 10, 880 + (1 - ease_out(a_doc)) * 300, alpha=a_doc, rot=-1.5)
            put(cv, self.vale, 780, 1250, alpha=ramp(u, 1.6, 2.0), rot=8 - 8 * ramp(u, 1.6, 2.1), scale=1.0)
            overlay(cv, (10, 10, 10), ramp(u, 2.7, 3.2))
        else:
            # the strike spreads across the banana zone
            cam = Cam(-74.18, 10.78, 1150, cy=720)
            self.draw_map(cv, cam, dark=True, show_rail=1.0, zone=0.6, labels=True)
            def dots(d, s):
                for i, (lo, la) in enumerate(STRIKE_TOWNS):
                    k = ramp(u, 3.3 + i * 0.18, 3.7 + i * 0.18)
                    if k <= 0:
                        continue
                    x, y = cam(lo, la)
                    r1 = 14 + 50 * k
                    d.ellipse((x - r1, y - r1, x + r1, y + r1), outline=(200, 60, 40, int(200 * (1 - k * 0.6))), width=4)
                    d.ellipse((x - 12, y - 12, x + 12, y + 12), fill=(210, 64, 44))
            cv.alpha_composite(layer(dots))
            overlay(cv, (10, 10, 10), 1 - ramp(u, 3.0, 3.5))
            # gathering workers along the bottom
            def crowd(d, s):
                for i in range(12):
                    x = (40 + i * 88) * s
                    h = (230 + (i * 37) % 50) * s
                    draw_person(d, x, 1320 * s, h, ["worker", "paper", "worker", "woman"][i % 4], seed=i + 20, step=i)
            cv.alpha_composite(with_alpha(layer(crowd, ss=2), ramp(u, 3.5, 4.2)))
        a1 = window(u, 0.3, 3.0, 0.35, 0.3)
        title(cv, "NOVIEMBRE DE 1928", 250, 84, face="serif", fill=INK, alpha=a1, tracking=3, shadow=False)
        a2 = window(u, 3.4, k1 - k0 + 0.1, 0.3, 0.25)
        title(cv, "NOVIEMBRE DE 1928", 250, 70, face="serif", fill=CREAM, alpha=a2, tracking=3)
        # the headline is stamped like a rubber stamp (cue: stamp sound at k1 - 1.0)
        ts = k1 - 1.0 - k0
        if u > ts - 0.05:
            k = ease_out((u - ts + 0.05) / 0.12)
            st = text_img("UNA HUELGA MASIVA", "bebas", 132, (196, 52, 40), 4)
            put(cv, st, CX, 420, scale=lerp(1.5, 1.0, k), alpha=k * 0.92 * (1 - ramp(u, k1 - k0 - 0.1, k1 - k0 + 0.1)), rot=-3)

    # ---- scene 3: the army
    def s_army(self, cv, t):
        a0, R = self.S["army"]
        u = t - a0
        tq = self.L["L3b"]["start"] - 0.25 - a0  # switch to the square
        if u < tq:
            cv.alpha_composite(self.bg_dark)
            # three distinct actors: company, state, army
            cards = [("UNITED FRUIT COMPANY", "empresa estadounidense", 0.0, (150, 140, 110)),
                     ("GOBIERNO DE COLOMBIA", "presidente Miguel Abadía Méndez", 0.35, (150, 140, 110)),
                     ("EJÉRCITO NACIONAL", "general Carlos Cortés Vargas", 0.9, (196, 156, 78))]
            for i, (a, b, delay, col) in enumerate(cards):
                k = ramp(u, 0.15 + delay, 0.6 + delay) * (1 - ramp(u, tq - 0.3, tq))
                y = 560 + i * 250
                box = layer(lambda d, s, a=a, b=b, col=col: (d.rectangle((0, 0, 820, 190), outline=col, width=3),
                                                              d.text((410, 70), a, font=FACES["sans"](54), fill=CREAM, anchor="mm"),
                                                              d.text((410, 136), b, font=FACES["oldr"](34), fill=(190, 180, 160), anchor="mm")), (822, 192))
                put(cv, box, CX + (1 - ease_out(k)) * 80, y, alpha=k)
            k = ramp(u, 0.75, 1.1) * (1 - ramp(u, tq - 0.3, tq))
            arrow = layer(lambda d, s: (d.line((410, 0, 410, 46), fill=GOLD, width=5), d.polygon([(392, 40), (428, 40), (410, 60)], fill=GOLD)), (820, 62))
            put(cv, arrow, CX, 560 + 250 + 125, alpha=k)
            put(cv, text_img("envió tropas", "italic", 34, GOLD), CX + 150, 560 + 250 + 125, alpha=k)
            put(cv, text_img("tres actores distintos", "type", 30, (150, 140, 120)), CX, 400, alpha=k * 0.9)
        else:
            v = u - tq
            span = R - a0 - tq
            # night square in Ciénaga
            if not hasattr(self, "_nightsky"):
                g = np.linspace(0, 1, H)[:, None, None]
                arr = (np.array([12, 16, 26]) * (1 - g) + np.array([44, 50, 62]) * g).repeat(W, 1)
                self._nightsky = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
            cv.alpha_composite(self._nightsky)
            sky = layer(lambda d, s: [d.ellipse((x, y, x + 3, y + 3), fill=(200, 200, 190, 120)) for x, y in
                                      np.random.default_rng(2).uniform((0, 0), (W, 700), (60, 2))])
            cv.alpha_composite(sky)
            push = ease(v / span)
            put(cv, self.station, W / 2, 784 - push * 10, scale=1.0 + push * 0.06)
            # lamps
            fl = 0.85 + 0.15 * math.sin(t * 13) * math.sin(t * 7.3)
            glow = layer(lambda d, s: [d.ellipse((x - 90, 700 - 90, x + 90, 700 + 90), fill=(240, 180, 90, int(60 * fl))) for x in (150, 930)])
            cv.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))
            ImageDraw.Draw(cv).rectangle((146, 700, 154, 1100), fill=(10, 10, 12))
            ImageDraw.Draw(cv).rectangle((926, 700, 934, 1100), fill=(10, 10, 12))
            ImageDraw.Draw(cv).rectangle((0, 1040, W, H), fill=(52, 50, 50))
            cv.alpha_composite(layer(lambda d, s: [d.ellipse((x - 260, 1000, x + 260, 1240), fill=(200, 150, 80, 40)) for x in (150, 930)]).filter(ImageFilter.GaussianBlur(40)))
            # crowd fills the square
            for depth, (people, col) in enumerate(self.crowd):
                fill = ramp(v, 0.1 + depth * 0.25, 1.4 + depth * 0.3)

                def cr(d, s, people=people, col=col, fill=fill):
                    for i, (x, y, h, kind, seed) in enumerate(people):
                        if i / len(people) > fill:
                            continue
                        draw_person(d, x * s, y * s, h * s, kind, seed, sil=col, step=0)
                lay = layer(cr)
                rim = Image.new("RGBA", lay.size, (210, 160, 90, 0))
                rim.putalpha(lay.getchannel("A").point(lambda v: int(v * 0.8)))
                cv.alpha_composite(rim, (-3, -2))
                cv.alpha_composite(lay)
            # soldiers form a line on the right
            ks = ease(clamp((v - 1.2) / 1.6))
            sx = lerp(W + 360, W - 250, ks)
            put(cv, self.soldiers_rim, sx + 3, 1138, alpha=ks * 0.9)
            put(cv, self.soldiers, sx, 1140, alpha=ks)
            # tension: rim light dims, red ink creeps along the bottom edge
            overlay(cv, (0, 0, 0), 0.25 * ramp(v, span - 1.5, span))
            title(cv, "5–6 DE DICIEMBRE DE 1928", 260, 74, face="serif", alpha=window(v, 0.2, span, 0.4, 0.05), tracking=2)
            title(cv, "CIÉNAGA, MAGDALENA", 360, 52, face="sans", fill=GOLD, alpha=window(v, 0.6, span, 0.4, 0.05), tracking=8)

    # ---- scene 4: aftermath
    def s_after(self, cv, t):
        R, e1 = self.S["after"]
        u = t - R
        cv.alpha_composite(Image.new("RGBA", (W, H), (6, 6, 7, 255)))
        if u < 0.5:  # the rupture: a thin red tear across black, then nothing
            k = 1 - ramp(u, 0.12, 0.5)
            ImageDraw.Draw(cv).rectangle((0, 960 - 3 * k, W * ease_out(u / 0.12), 960 + 3 * k), fill=(*RED, 255))
            return
        # the empty square at grey dawn
        k = ramp(u, 1.2, 2.6) * (1 - ramp(u, e1 - R - 0.5, e1 - R))
        if k > 0:
            sc = Image.new("RGBA", (W, H), (70, 74, 76, 255))
            put(sc, self.station_day, W / 2, 784, scale=1.03)
            ImageDraw.Draw(sc).rectangle((0, 1040, W, H), fill=(92, 90, 84))
            put(sc, self.tools, 330, 1240, scale=1.0)
            for i, (x, y, rot, s) in enumerate(self.papers):
                drift = (u * 14 * (1 + i % 3)) % 60
                put(sc, self.news_small if i == 0 else self.vale if i == 4 else self.doc, x + drift, y - (i % 2) * 8, scale=0.09 * s * (3 if i == 0 else 1.6 if i == 4 else 1), rot=rot)
            cv.alpha_composite(with_alpha(sc, k * (1 - 0.65 * ramp(u, 3.2, 3.8))))
            a = window(u, 2.0, 3.6, 0.3, 0.3)
            put(cv, text_img("DETENCIONES · PERSECUCIÓN", "type", 40, CREAM), CX, 420, alpha=a)
        # newspaper emerges from darkness behind the counter
        tn = 3.4
        kn = ramp(u, tn, tn + 1.0)
        if kn > 0:
            put(cv, self.news, CX, 1010, scale=0.86 + 0.04 * kn, alpha=kn * 0.85, rot=-2)
            overlay(cv, (0, 0, 0), 0.35 * kn)
            self.counter(cv, u - tn)

    def counter(self, cv, v):
        """Creative device: a split-flap counter that can never settle on one number.
        47 = deaths acknowledged by the military commander; estimates reach 'more than 1,000'."""
        L4 = self.L["L4"]
        span = L4["end"] - self.S["after"][0] - 3.4
        t47, t1000, tq = 0.5, span * 0.55, span * 0.85
        if v < t47 + 0.6:
            val, settled = int(abs(math.sin(v * 37)) * 9999), v > t47 + 0.45
            val = 47 if settled else val
        elif v < t1000:
            val, settled = 47, True
        elif v < t1000 + 0.6:
            val, settled = (1000 if v > t1000 + 0.45 else int(47 + (v - t1000) * 1600 + abs(math.sin(v * 41)) * 500)), v > t1000 + 0.45
        elif v < tq:
            val, settled = 1000, True
        else:
            val, settled = None, False
        digits = list(f"{val:>4d}") if val is not None else ["?"] * 4
        if val is not None and not settled:
            digits = list(f"{val:04d}")
        tiles = len(digits)
        tw, th, gap = 150, 210, 18
        x0 = CX - (tiles * tw + (tiles - 1) * gap) / 2 + tw / 2
        for i, ch in enumerate(digits):
            spin = val is None and abs(math.sin(v * 11 + i)) > 0.5
            tile = layer(lambda d, s, ch=ch, spin=spin: (
                d.rounded_rectangle((0, 0, tw, th), radius=12, fill=(24, 22, 20)),
                d.line((0, th / 2, tw, th / 2), fill=(6, 6, 6), width=4),
                d.text((tw / 2, th / 2 + (8 if spin else 0)), ch, font=FACES["bebas"](190), fill=CREAM if ch != "?" else (210, 70, 54), anchor="mm")), (tw, th))
            put(cv, tile, x0 + i * (tw + gap), 900, scale=1.0 if not spin else 0.98)
        if v > t47 + 0.45 and v < t1000:
            put(cv, text_img("muertos reconocidos por el jefe militar", "italic", 38, CREAM), CX, 1090, alpha=ramp(v, t47 + 0.45, t47 + 0.8))
        if t1000 + 0.45 < v < tq:
            put(cv, text_img("más de mil, según otras estimaciones", "italic", 38, CREAM), CX, 1090, alpha=ramp(v, t1000 + 0.45, t1000 + 0.8))
        a = ramp(v, tq, tq + 0.4)
        title(cv, "LAS CIFRAS", 280, 96, face="serif", alpha=a)
        title(cv, "SIGUEN EN DEBATE", 390, 96, face="serif", alpha=a, fill=(226, 90, 70))

    # ---- scene 5: Gaitán
    def s_gaitan(self, cv, t):
        g0, g1 = self.S["gaitan"]
        u = t - g0
        cv.alpha_composite(self.bg_paper)
        overlay(cv, (40, 36, 30), 0.15)
        # printed letters fly in from the newsprint to spell his name
        name = "JORGE ELIÉCER GAITÁN"
        f = FACES["serif"](86)
        total = f.getlength(name)
        x = CX - total / 2
        rng = np.random.default_rng(4)
        for i, ch in enumerate(name):
            w = f.getlength(ch)
            k = ease_out(clamp((u - 0.1 - i * 0.03) / 0.7))
            sx, sy = rng.uniform(-200, W + 200), rng.uniform(-300, H + 300)
            if ch != " ":
                im = text_img(ch, "serif", 86, INK)
                put(cv, im, lerp(sx, x + w / 2, k), lerp(sy, 300, k), alpha=k, rot=(1 - k) * rng.uniform(-90, 90))
            x += w
        tf, tc, tn = (self.S[k] - g0 for k in ("file", "congreso", "country"))
        out = 1 - ramp(u, tn - 0.25, tn + 0.15)  # portrait + file give way to the map
        p = ramp(u, 0.5, 1.9)
        portrait = ink_reveal(self.portrait, p)
        mv = ease(clamp((u - tf + 0.1) / 0.6))
        if portrait is not None:
            put(cv, portrait, lerp(CX, 300, mv), lerp(760, 640, mv), scale=lerp(0.92, 0.55, mv), alpha=out)
        put(cv, text_img("ILUSTRACIÓN", "sans", 22, (110, 100, 86), 4), lerp(880, 300, mv), lerp(1120, 830, mv), alpha=p * out)
        # the investigation file and the denunciation
        kf = ramp(u, tf, tf + 0.5)
        if kf > 0:
            fold = layer(lambda d, s: (d.rectangle((0, 30, 640, 420), fill=(176, 146, 92)),
                                       d.rectangle((0, 0, 230, 40), fill=(176, 146, 92)),
                                       d.text((320, 130), "EXPEDIENTE", font=FACES["old"](64), fill=INK, anchor="mm"),
                                       d.text((320, 210), "ZONA BANANERA · 1928", font=FACES["type"](38), fill=INK, anchor="mm"),
                                       d.text((320, 290), "testimonios · documentos", font=FACES["type"](30), fill=(70, 56, 40), anchor="mm")), (640, 420))
            put(cv, fold, CX + 110, 1010 + (1 - ease_out(kf)) * 400, alpha=kf * out, rot=3, scale=0.92)
        kd = ramp(u, tf + 0.3, tf + 0.7)
        title(cv, "LA DENUNCIA", 440, 104, face="bebas", fill=RED, alpha=kd * out, tracking=10, shadow=False)
        if u > tc - 0.05:  # stamped on the file as the narration says "Congreso"
            k = ease_out((u - tc + 0.05) / 0.12)
            st = layer(lambda d, s: (d.rounded_rectangle((4, 4, 720, 150), radius=14, outline=(170, 40, 32), width=6),
                                     d.text((362, 52), "DEBATE EN LA CÁMARA", font=FACES["bebas"](70), fill=(170, 40, 32), anchor="mm"),
                                     d.text((362, 112), "SEPTIEMBRE DE 1929", font=FACES["sans"](40), fill=(170, 40, 32), anchor="mm")), (724, 154))
            put(cv, st, CX + 90, 1060, scale=lerp(1.4, 0.82, k), alpha=0.92 * k * out, rot=-6)
        # national attention: the denunciation travels across the country
        kc = ramp(u, tn - 0.1, tn + 0.35)
        if kc > 0:
            cam = Cam(-73.2, 4.6, 56, cx=CX + 40, cy=820)
            mp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            self.draw_map(mp, cam, labels=False)

            def lines(d, s):
                ox, oy = cam(-74.07, 4.71)
                for i, (nm, (lo, la)) in enumerate(CITIES.items()):
                    k = ramp(u, tn + 0.2 + i * 0.1, tn + 0.6 + i * 0.1)
                    x, y = cam(lo, la)
                    d.line((ox, oy, lerp(ox, x, k), lerp(oy, y, k)), fill=(*RED, 220), width=4)
                    if k > 0.95:
                        d.rectangle((x - 10, y - 13, x + 10, y + 13), fill=(236, 228, 210), outline=INK, width=2)
                d.ellipse((ox - 13, oy - 13, ox + 13, oy + 13), fill=RED)
            mp.alpha_composite(layer(lines))
            put(cv, mp, W / 2, H / 2, alpha=kc, scale=lerp(0.94, 1.0, kc))
            put(cv, text_img("BOGOTÁ", "sans", 30, INK, 3), cam(-74.07, 4.71)[0] - 85, cam(-74.07, 4.71)[1] - 4, alpha=kc)
            title(cv, "ANTE TODO EL PAÍS", 450, 72, face="sans", fill=RED, alpha=ramp(u, tn + 0.1, tn + 0.5), tracking=6, shadow=False)

    # ---- scene 6: lesson + cliffhanger
    def s_lesson(self, cv, t):
        l0 = self.S["lesson"][0]
        fc = self.S["final_card"]
        u = t - l0
        if t < fc + 0.6:
            cv.alpha_composite(self.bg_dark)
            push = 1 + 0.05 * ease(u / (fc - l0 + 0.6))
            comp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            put(comp, self.news, 400, 700, scale=0.62, rot=-4, alpha=0.9)
            overlay(comp, (0, 0, 0), 0.3)
            put(comp, self.portrait, 700, 860, scale=0.6)
            put(comp, self.tools, 330, 1110, scale=1.1)
            # the railway becomes a timeline that runs on into darkness
            def tl(d, s):
                y = 1250
                d.line((60, y, W + 20, y), fill=GOLD, width=4)
                for x in range(60, W + 20, 46):
                    d.line((x, y - 12, x, y + 12), fill=(120, 96, 50), width=3)
                for x, lab in ((180, "1928"), (480, "1929")):
                    d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=GOLD)
                    d.text((x, y - 50), lab, font=FACES["bebas"](56), fill=CREAM, anchor="mm")
                d.text((800, y - 50), "· · ·", font=FACES["bebas"](56), fill=(150, 130, 90), anchor="mm")
            comp.alpha_composite(layer(tl))
            fadeR = layer(lambda d, s: [d.line((x, 0, x, H), fill=(6, 6, 6, int(255 * clamp((x - 640) / 440)))) for x in range(640, W, 2)])
            comp.alpha_composite(fadeR)
            put(cv, comp, W / 2, H / 2, scale=push, alpha=ramp(u, 0.0, 0.5))
            # the page folds into darkness
            kf = ramp(t, fc - 0.35, fc + 0.6)
            if kf > 0:
                ImageDraw.Draw(cv).rectangle((0, 0, W, H * kf), fill=(6, 6, 6))
                ImageDraw.Draw(cv).rectangle((0, H * kf - 6, W, H * kf), fill=(60, 54, 44))
        else:
            cv.alpha_composite(Image.new("RGBA", (W, H), (6, 6, 6, 255)))
        # end card
        if t > fc:
            text = "LA HISTORIA NO TERMINÓ AQUÍ."
            v = t - fc
            n = int(len(text) * clamp(v / 1.2))
            st = self.S["sting"]
            glow = ramp(t, st, st + 0.2) * (1 - ramp(t, st + 0.4, st + 1.6))
            col = mix(CREAM, (240, 200, 120), glow)
            lines_ = ["LA HISTORIA", "NO TERMINÓ AQUÍ."]
            shown = text[:n]
            l1 = shown[:11]
            l2 = shown[12:] if n > 12 else ""
            title(cv, l1, 880, 110, face="serif", fill=col, alpha=1.0) if l1 else None
            title(cv, l2, 1010, 110, face="serif", fill=col, alpha=1.0) if l2 else None
            put(cv, text_img("Masacre de las Bananeras · 1928", "type", 32, (150, 140, 120)), CX, 1160, alpha=ramp(t, st, st + 0.5))

    # ---- frame
    def frame(self, f):
        t = f / FPS
        S = self.S
        cv = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        if t < S["setting"][1]:
            self.s_setting(cv, t)
        elif t < S["strike"][1]:
            self.s_strike(cv, t)
        elif t < S["army"][1]:
            self.s_army(cv, t)
        elif t < S["after"][1]:
            self.s_after(cv, t)
        elif t < S["gaitan"][1]:
            self.s_gaitan(cv, t)
        else:
            self.s_lesson(cv, t)
        # short dips between sections hide the cuts (not at the rupture: that cut is meant to be hard)
        for key in ("setting", "strike", "after", "gaitan"):
            e = S[key][1]
            overlay(cv, (0, 0, 0), 0.6 * (1 - clamp(abs(t - e) / 0.12)))
        draw_subs(cv, t, self.subs)
        return self.film.apply(cv, f)


# ---------------------------------------------------------------- render
G = None


def _init(timing):
    global G
    G = Film40(timing)


def _render(f):
    return G.frame(f).tobytes()


def srt(chunks):
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(chunks, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", help="comma-separated times (s) to export as PNG stills")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    args = ap.parse_args()
    timing = json.loads((OUT / "narration_timing.json").read_text())
    if args.frames:
        _init(timing)
        (OUT / "preview").mkdir(exist_ok=True)
        for s in args.frames.split(","):
            f = int(float(s) * FPS)
            G.frame(f).save(OUT / "preview" / f"t{float(s):05.2f}.png")
        return
    n = int(timing["duration"] * FPS)
    (OUT / "subtitles.srt").write_text(srt(subtitle_chunks(timing["lines"])) + "\n", encoding="utf-8")
    dst = OUT / "bananeras_1080x1920.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-i", str(OUT / "mix.wav"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-maxrate", "14M", "-bufsize", "28M",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(dst)], stdin=subprocess.PIPE)
    with Pool(args.jobs, initializer=_init, initargs=(timing,)) as pool:
        for i, buf in enumerate(pool.imap(_render, range(n), chunksize=4)):
            ff.stdin.write(buf)
            if i % 150 == 0:
                print(f"frame {i}/{n}", flush=True)
    ff.stdin.close()
    ff.wait()
    print("wrote", dst)


if __name__ == "__main__":
    main()
