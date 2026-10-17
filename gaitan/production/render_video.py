#!/usr/bin/env python3
"""Render the 1080x1920 / 30 fps documentary short.

Archival photographs are read from assets/archival/ (see assets/manifest.json).
Any photo that is missing is replaced by a clearly labelled illustrated plate
("ILUSTRACIÓN") -- never by a fake photograph.

Reads production/timeline.json and out/narration_timing.json (from build_audio.py),
muxes out/mix.wav and writes out/gaitan_tiktok_1080x1920.mp4.
"""
import argparse
import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
FONTS = ROOT / "assets" / "fonts"
ARCH = ROOT / "assets" / "archival"
W, H = 1080, 1920
FPS = 30

INK = (16, 14, 13)
PAPER = (226, 219, 203)
RED = (178, 34, 30)
EMBER = (235, 120, 40)
WHITE = (242, 238, 230)
SAFE_X0, SAFE_X1 = 90, 960          # right margin leaves room for TikTok buttons
SUB_Y = 1335                        # subtitles sit above the caption / music area

rng = np.random.default_rng(9)


# ---------------------------------------------------------------- easing / util
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ramp(t, t0, t1):
    return ease((t - t0) / max(t1 - t0, 1e-6))


@lru_cache(None)
def font(name, size, var=None):
    f = ImageFont.truetype(str(FONTS / name), size)
    if var:
        f.set_variation_by_name(var)
    return f


def serif(size, var="Black"):
    return font("PlayfairDisplay[wght].ttf", size, var)


def sans(size, var="SemiBold"):
    return font("Oswald[wght].ttf", size, var)


def typew(size):
    return font("SpecialElite-Regular.ttf", size)


@lru_cache(None)
def text_img(text, fkey, size, fill, stroke=0, stroke_fill=(0, 0, 0), tracking=0, var=None):
    f = {"serif": serif, "sans": sans, "type": lambda s, v=None: typew(s)}[fkey](size, var) if var else \
        {"serif": serif, "sans": sans, "type": typew}[fkey](size)
    if tracking:
        widths = [f.getbbox(c)[2] - f.getbbox(c)[0] if c != " " else size * 0.28 for c in text]
        total = int(sum(widths) + tracking * (len(text) - 1)) + 2 * stroke + 8
        asc, desc = f.getmetrics()
        im = Image.new("RGBA", (total, asc + desc + 2 * stroke + 8), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x = stroke + 4
        for c, w in zip(text, widths):
            d.text((x - (f.getbbox(c)[0] if c != " " else 0), stroke + 4), c, font=f, fill=fill,
                   stroke_width=stroke, stroke_fill=stroke_fill)
            x += w + tracking
        return im
    bb = f.getbbox(text, stroke_width=stroke)
    im = Image.new("RGBA", (bb[2] - bb[0] + 8, bb[3] - bb[1] + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4 - bb[0], 4 - bb[1]), text, font=f, fill=fill,
                            stroke_width=stroke, stroke_fill=stroke_fill)
    return im


def with_alpha(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def put(canvas, im, cx, cy, scale=1.0, alpha=1.0, rot=0.0, resample=Image.BILINEAR):
    """Composite RGBA `im` centred at (cx, cy), cropping safely at the canvas edges."""
    if alpha <= 0.002:
        return
    if abs(scale - 1) > 1e-3:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), resample)
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
    """Blend a flat colour over the whole canvas (ImageDraw would overwrite, not blend)."""
    if a <= 0.002:
        return
    canvas.alpha_composite(Image.new("RGBA", canvas.size, (*color[:3], int(255 * clamp(a)))))


def drawn(canvas, fn):
    """Run ImageDraw calls on a transparent layer and alpha-blend it onto the canvas."""
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    fn(ImageDraw.Draw(lay))
    canvas.alpha_composite(lay)


# ---------------------------------------------------------------- textures
def noise_field(w, h, scale, seed):
    r = np.random.default_rng(seed)
    small = r.random((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def paper_texture(color, dark=False, seed=1):
    base = np.ones((H, W, 3), np.float32) * np.array(color, np.float32)
    n = noise_field(W, H, 6, seed) * 0.5 + noise_field(W, H, 60, seed + 1) * 0.5
    fib = noise_field(W, H, 2, seed + 2)
    amt = 10 if dark else 22
    base += ((n - 0.5) * amt + (fib - 0.5) * amt * 0.5)[..., None]
    if not dark:  # foxing / stains
        st = np.clip(noise_field(W, H, 180, seed + 3) - 0.62, 0, 1) * 90
        base -= st[..., None] * np.array([0.6, 0.8, 1.0])
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")


def torn_edge_mask(w, h, seed, rough=10):
    r = np.random.default_rng(seed)
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    pts = []
    for x in np.linspace(0, w, 40):
        pts.append((x, r.uniform(0, rough)))
    for y in np.linspace(0, h, 60):
        pts.append((w - r.uniform(0, rough), y))
    for x in np.linspace(w, 0, 40):
        pts.append((x, h - r.uniform(0, rough)))
    for y in np.linspace(h, 0, 60):
        pts.append((r.uniform(0, rough), y))
    d.polygon(pts, fill=255)
    return m


INK_NOISE = None


def ink_reveal(im, progress, seed=0):
    """Reveal an RGBA layer through an organic ink-bleed mask (progress 0..1)."""
    global INK_NOISE
    if progress >= 0.999:
        return im
    if INK_NOISE is None:
        INK_NOISE = noise_field(W, H, 40, 77) * 0.6 + noise_field(W, H, 8, 78) * 0.4
    n = Image.fromarray((INK_NOISE * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR)
    n = np.asarray(n, np.float32) / 255
    yy, xx = np.mgrid[0:im.height, 0:im.width]
    radial = np.hypot((xx - im.width / 2) / im.width, (yy - im.height / 2) / im.height)
    field = radial * 0.9 + n * 0.55
    thr = progress * 1.25
    m = np.clip((thr - field) * 14, 0, 1)
    a = np.asarray(im.getchannel("A"), np.float32) / 255 * m
    out = im.copy()
    out.putalpha(Image.fromarray((a * 255).astype(np.uint8)))
    return out


# ---------------------------------------------------------------- archival plates
def load_photo(name, width, border=26, seed=3, rot=0.0):
    """B&W print with paper border and torn edge, or None if the file is missing."""
    p = ARCH / name
    if not p.exists():
        return None
    im = Image.open(p).convert("L")
    im = ImageOps.autocontrast(im, cutoff=0.6)
    h = int(im.height * width / im.width)
    im = im.resize((width, h), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 60, 2))
    # gentle film curve + neutral-warm black-and-white tone (no colourisation)
    arr = np.asarray(im, np.float32) / 255
    arr = np.clip((arr - 0.5) * 1.08 + 0.5, 0, 1) ** 1.05
    rgb = np.stack([arr * 236 + 12, arr * 230 + 11, arr * 218 + 10], -1)
    photo = Image.fromarray(rgb.astype(np.uint8))
    pw, ph = width + 2 * border, h + 2 * border
    card = Image.new("RGBA", (pw, ph), (*PAPER, 255))
    card.paste(photo, (border, border))
    card.putalpha(torn_edge_mask(pw, ph, seed, rough=8))
    shadow = Image.new("RGBA", (pw + 60, ph + 60), (0, 0, 0, 0))
    sm = Image.new("L", (pw, ph), 150)
    shadow.paste((0, 0, 0, 255), (30, 34), sm)
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    shadow.alpha_composite(card, (30, 30))
    return shadow.rotate(rot, resample=Image.BICUBIC, expand=True) if rot else shadow


def label(canvas, text, x, y, alpha=1.0, color=WHITE):
    """Small caption on a dark tag, readable over any background."""
    im = text_img(text, "sans", 26, (*WHITE, 255), tracking=4, var="Regular")
    tag = Image.new("RGBA", (im.width + 28, im.height + 10), (8, 8, 8, 170))
    tag.alpha_composite(im, (14, 5))
    put(canvas, tag, x, y, alpha=alpha * 0.9)


# ---------------------------------------------------------------- illustrations (fallbacks + graphics)
def newspaper_page(seed, blank=None):
    """Newsprint with columns rendered as grey text bars (no invented copy)."""
    r = np.random.default_rng(seed)
    pg = paper_texture(PAPER, seed=seed)
    d = ImageDraw.Draw(pg)
    d.rectangle((60, 120, W - 60, 128), fill=(*INK, 255))
    d.rectangle((60, 136, W - 60, 138), fill=(*INK, 255))
    cols = 4
    cw = (W - 120 - (cols - 1) * 28) / cols
    for c in range(cols):
        x0 = 60 + c * (cw + 28)
        y = 170
        while y < H - 120:
            if blank and blank[0] <= y <= blank[1]:
                y = blank[1] + 1
                continue
            if r.random() < 0.06:
                y += 40
                continue
            wfrac = 1.0 if r.random() > 0.15 else r.uniform(0.3, 0.8)
            d.rectangle((x0, y, x0 + cw * wfrac, y + 7), fill=(70, 66, 60, int(r.uniform(90, 140))))
            y += 17
        if c < cols - 1:
            for y0, y1 in ((170, blank[0] - 10), (blank[1] + 10, H - 120)) if blank else ((170, H - 120),):
                d.line((x0 + cw + 14, y0, x0 + cw + 14, y1), fill=(60, 56, 50, 120), width=1)
    return pg


def microphone(size=360):
    im = Image.new("RGBA", (size, int(size * 1.7)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = size // 2
    w, h = int(size * 0.42), int(size * 0.62)
    d.rounded_rectangle((cx - w // 2, 30, cx + w // 2, 30 + h), radius=w // 2, outline=WHITE, width=10)
    for i in range(1, 9):
        y = 30 + h * i / 9
        half = (w / 2 - 10) * math.sqrt(max(0, 1 - ((y - 30 - h / 2) / (h / 2)) ** 2))
        d.line((cx - half, y, cx + half, y), fill=(*WHITE, 200), width=4)
    d.arc((cx - w // 2 - 40, 30 + h * 0.35, cx + w // 2 + 40, 30 + h + 50), 0, 180, fill=WHITE, width=10)
    d.line((cx, 30 + h + 50, cx, im.height - 50), fill=WHITE, width=12)
    d.rounded_rectangle((cx - 110, im.height - 60, cx + 110, im.height - 30), radius=12, fill=WHITE)
    return im


def crowd_layers():
    """Rally crowd as ink silhouettes in perspective, split into 3 depth layers for parallax."""
    r = np.random.default_rng(20)
    horizon, n = 900, 950
    HH = H + 320
    ys = np.sort(horizon + (HH - horizon) * r.random(n) ** 1.6)
    layers = [Image.new("RGBA", (W + 240, HH), (0, 0, 0, 0)) for _ in range(3)]
    draws = [ImageDraw.Draw(l) for l in layers]
    for y in ys:
        depth = min(1.0, (y - horizon) / (H - horizon))          # 0 far .. 1 near
        k = 0 if depth < 0.33 else (1 if depth < 0.66 else 2)
        rr = 9 + depth ** 1.2 * 64
        x = r.uniform(-40, W + 240)
        v = int(70 - depth * 55)
        shade = (v, v - 3, v - 6, 255)
        edge = (min(v + 40, 160), min(v + 36, 150), min(v + 30, 140), 255)
        d = draws[k]
        d.rounded_rectangle((x - rr * 1.9, y + rr * 0.75, x + rr * 1.9, y + rr * 7), radius=int(rr * 0.9), fill=shade, outline=edge)
        d.ellipse((x - rr * 0.78, y - rr, x + rr * 0.78, y + rr), fill=shade, outline=edge)
        if r.random() < 0.22:  # hats of the period
            d.ellipse((x - rr * 1.3, y - rr * 0.6, x + rr * 1.3, y - rr * 0.2), fill=shade)
            d.rectangle((x - rr * 0.72, y - rr * 1.3, x + rr * 0.72, y - rr * 0.45), fill=shade)
        if r.random() < 0.035:  # raised arm
            d.line((x + rr * 1.4, y + rr, x + rr * 2.2, y - rr * 4.5), fill=shade, width=max(2, int(rr * 0.7)))
            d.ellipse((x + rr * 1.8, y - rr * 5.2, x + rr * 2.7, y - rr * 4.2), fill=shade)
    return layers


def city_skyline():
    im = Image.new("RGBA", (W + 160, 900), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = np.random.default_rng(48)
    x = 0
    while x < W + 160:
        bw = r.uniform(70, 170)
        bh = r.uniform(160, 460)
        d.rectangle((x, 900 - bh, x + bw, 900), fill=(12, 10, 10, 255))
        for wy in np.arange(900 - bh + 30, 900 - 40, 42):
            for wx in np.arange(x + 14, x + bw - 20, 30):
                if r.random() < 0.35:
                    d.rectangle((wx, wy, wx + 12, wy + 20), fill=(210, 110, 40, int(r.uniform(90, 220))))
        if r.random() < 0.18:  # church tower
            tx = x + bw / 2
            d.rectangle((tx - 22, 900 - bh - 150, tx + 22, 900 - bh), fill=(12, 10, 10, 255))
            d.polygon([(tx - 28, 900 - bh - 150), (tx, 900 - bh - 230), (tx + 28, 900 - bh - 150)], fill=(12, 10, 10, 255))
        x += bw + r.uniform(-10, 8)
    return im


FIRE_N = None


def fire_layer(t, base_y, height=700, intensity=1.0):
    """Smooth, flickering fire glow rising above `base_y` (behind skyline or photo)."""
    global FIRE_N
    if FIRE_N is None:
        n = noise_field(W // 6, 3 * H // 6, 14, 5)
        FIRE_N = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), np.float32) / 255
    hh = H // 6
    off = int(t * 22) % (FIRE_N.shape[0] - hh)
    n = FIRE_N[FIRE_N.shape[0] - hh - off: FIRE_N.shape[0] - off]
    y = np.linspace(0, H, hh)[:, None]
    up = np.clip((base_y - y) / height, 0, None)
    prof = np.exp(-up * 2.4) * (y < base_y + 40)
    flick = 0.85 + 0.15 * math.sin(t * 7.3) * math.sin(t * 3.1)
    f = np.clip(prof * (0.55 + 0.9 * (n - 0.35)) * flick * intensity, 0, 1)
    rgb = np.stack([np.full_like(f, 255), 60 + f * 150, 20 + f ** 2 * 60], -1)
    a = f * 255
    im = Image.fromarray(np.dstack([rgb, a]).astype(np.uint8), "RGBA").resize((W, H), Image.BICUBIC)
    return im


class Embers:
    def __init__(self, n=140):
        self.p = np.column_stack([rng.uniform(0, W, n), rng.uniform(H * 0.3, H, n),
                                  rng.uniform(-20, 20, n), rng.uniform(60, 220, n), rng.uniform(1.5, 4.5, n),
                                  rng.uniform(0, 10, n)])

    def draw(self, canvas, t, alpha):
        if alpha <= 0:
            return
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        for x, y, vx, vy, s, ph in self.p:
            yy = (y - vy * t) % H
            xx = x + vx * t + 25 * math.sin(t * 1.3 + ph)
            fl = 0.5 + 0.5 * math.sin(t * 9 + ph * 3)
            d.ellipse((xx - s, yy - s, xx + s, yy + s), fill=(255, int(140 + 80 * fl), 60, int(255 * alpha * (0.4 + 0.6 * fl))))
        canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(1.2)))


# ---------------------------------------------------------------- film finishing
class Film:
    def __init__(self):
        self.grain = [(rng.standard_normal((H // 2, W // 2)) * 9).astype(np.float32) for _ in range(6)]
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.hypot((xx - W / 2) / (W * 0.62), (yy - H / 2) / (H * 0.58))
        self.vig = np.clip(1 - (r ** 2.2) * 0.55, 0.25, 1).astype(np.float32)[..., None]

    def apply(self, img, f, t, strength=1.0):
        a = np.asarray(img.convert("RGB"), np.float32)
        g = self.grain[f % 6]
        g = np.repeat(np.repeat(g, 2, 0), 2, 1)
        flick = 1 + 0.018 * math.sin(f * 2.1) * math.sin(f * 0.77)
        a = a * flick * self.vig + g[..., None] * strength
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(out)
        r = np.random.default_rng(f * 7 + 1)
        for _ in range(r.integers(0, 4)):  # dust
            x, y, s = r.uniform(0, W), r.uniform(0, H), r.uniform(1, 3.5)
            c = int(r.choice([20, 230]))
            d.ellipse((x - s, y - s, x + s, y + s), fill=(c, c, c))
        if r.random() < 0.10:  # scratch
            x = r.uniform(80, W - 80)
            d.line((x, 0, x + r.uniform(-8, 8), H), fill=(200, 196, 188), width=1)
        return out


# ---------------------------------------------------------------- subtitles
def subtitle_chunks(lines, max_chars=46):
    """Split narration lines into phrase-aligned chunks (≤2 short lines) timed by character share."""
    import re
    chunks = []
    for ln in lines:
        clauses = [c.strip() for c in re.findall(r"[^,.;:?!]+[,.;:?!]?", ln["sub"]) if c.strip()]
        groups = []
        for cl in clauses:
            if groups and len(groups[-1]) + 1 + len(cl) <= max_chars:
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
        nxt = chunks[i + 1][0] if i + 1 < len(chunks) else b + 0.6
        out.append((a, min(nxt, b + 0.6), txt))
    return out


def wrap(txt, max_chars=26):
    """One line if it fits, else two balanced lines."""
    if len(txt) <= max_chars:
        return [txt]
    ws = txt.split()
    best = min(range(1, len(ws)), key=lambda i: max(len(" ".join(ws[:i])), len(" ".join(ws[i:]))))
    return [" ".join(ws[:best]), " ".join(ws[best:])]


@lru_cache(None)
def subtitle_img(txt):
    f = sans(56, "SemiBold")
    lines = wrap(txt)
    lh = 72
    wmax = max(f.getbbox(l, stroke_width=6)[2] for l in lines) + 40
    im = Image.new("RGBA", (wmax + 40, lh * len(lines) + 34), (0, 0, 0, 0))
    plate = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle((6, 4, im.width - 6, im.height - 4), radius=18, fill=(6, 6, 6, 150))
    im.alpha_composite(plate.filter(ImageFilter.GaussianBlur(4)))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        bw = f.getbbox(l, stroke_width=6)[2]
        d.text(((wmax + 40 - bw) / 2, 12 + i * lh), l, font=f, fill=(250, 248, 242),
               stroke_width=6, stroke_fill=(8, 8, 8))
    return im


def draw_subs(canvas, t, chunks):
    for a, b, txt in chunks:
        if a - 0.05 <= t < b:
            im = subtitle_img(txt)
            k = ease_out((t - a + 0.05) / 0.15)
            cx = (SAFE_X0 + SAFE_X1) / 2
            assert im.width <= SAFE_X1 - SAFE_X0 + 60, txt
            put(canvas, im, cx, SUB_Y + im.height / 2 + (1 - k) * 12, alpha=k)
            break


# ---------------------------------------------------------------- scenes
class Scenes:
    def __init__(self, tl, timing):
        self.tl, self.S = tl, tl["sections"]
        self.L = {l["id"]: l for l in timing["lines"]}
        self.rupture = tl["rupture"]
        self.dark = paper_texture((22, 20, 19), dark=True, seed=4)
        self.news1 = newspaper_page(11, blank=(400, 1020))
        self.news2 = newspaper_page(12, blank=(380, 1210))
        cx = (SAFE_X0 + SAFE_X1) / 2
        self.cx = cx
        self.portrait = load_photo("gaitan_1936.jpg", 560, seed=5)
        self.portrait_big = load_photo("gaitan_1936.jpg", 820, border=0, seed=6)
        self.crowd_photo = load_photo("marcha_del_silencio_1948.jpg", 820, seed=7, rot=-1.5)
        self.tram_photo = load_photo("bogotazo_tranvia_1948.jpg", 860, seed=8, rot=1.2)
        self.mic = microphone()
        self.crowd = crowd_layers()
        self.city = city_skyline()
        self.embers = Embers()
        self.used_fallback = {
            "portrait": self.portrait is None,
            "crowd": self.crowd_photo is None,
            "bogotazo": self.tram_photo is None,
        }

    # -- shared pieces
    def name_block(self, canvas, cx, cy, alpha, scale=1.0):
        for i, (txt, size) in enumerate((("JORGE", 120), ("ELIÉCER", 120), ("GAITÁN", 176))):
            im = text_img(txt, "serif", size, (*WHITE, 255), tracking=6, var="Black")
            put(canvas, im, cx, cy + (i - 1) * 150 * scale + (40 if i == 2 else 0) * scale, scale=scale, alpha=alpha)

    def kicker(self, canvas, text, y, alpha, color=WHITE):
        im = text_img(text, "sans", 34, (*color, 255), tracking=10, var="Medium")
        put(canvas, im, self.cx, y, alpha=alpha)
        w = im.width / 2 + 30
        if alpha > 0.05:
            a = int(255 * alpha)
            drawn(canvas, lambda d: (d.line((self.cx - w - 70, y, self.cx - w, y), fill=(*RED, a), width=3),
                                     d.line((self.cx + w, y, self.cx + w + 70, y), fill=(*RED, a), width=3)))

    # -- 0: hook
    def hook(self, c, t):
        s0, s1 = self.S["hook"]
        c.alpha_composite(self.dark)
        self.kicker(c, "COLOMBIA · 1948", 240, ramp(t, 0.2, 0.9))
        push = 1.0 + 0.06 * (t - s0) / (s1 - s0)
        if self.portrait:
            im = ink_reveal(self.portrait, ramp(t, 0.05, 1.3))
            put(c, im, self.cx, 735, scale=push)
            a = ramp(t, self.L["L02"]["start"] - 0.1, self.L["L02"]["start"] + 0.5)
            put(c, text_img("JORGE ELIÉCER GAITÁN", "serif", 62, (*WHITE, 255), tracking=2, var="Black"),
                self.cx, 1215, alpha=a)
        else:
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            self.name_block(lay, self.cx, 760, 1.0, scale=push)
            c.alpha_composite(ink_reveal(lay, ramp(t, 0.05, 1.5)))
        out = 1 - ramp(t, s1 - 0.25, s1)
        if out < 1:
            overlay(c, (0, 0, 0), (255 * (1 - out)) / 255)

    # -- 1: rise (Bogotá -> Roma -> the people)
    def rise(self, c, t):
        s0, s1 = self.S["rise"]
        c.alpha_composite(self.dark)
        k = ease_out((t - s0) / 0.45)
        pg = self.news1
        put(c, pg, self.cx + 14, H / 2 + (1 - k) * 900, scale=0.94, rot=-2.2)
        overlay(c, (10, 8, 8), 0.35)
        lt = self.L["L04"]["start"]
        cards = (("BOGOTÁ", "Universidad Nacional · Derecho", 520, s0 + 0.3),
                 ("ROMA", "Real Universidad de Roma · 1926", 860, s0 + 1.9))
        for name, sub, y, ta in cards:
            a = ramp(t, ta, ta + 0.25) * (1 - ramp(t, lt - 0.3, lt))
            n = int(len(name) * clamp((t - ta) / 0.5))
            if n:
                put(c, text_img(name[:n], "type", 120, (*INK, 255)), self.cx, y, alpha=a)
            put(c, text_img(sub, "sans", 34, (*RED, 255), tracking=3, var="Medium"), self.cx, y + 92,
                alpha=ramp(t, ta + 0.5, ta + 0.8) * (1 - ramp(t, lt - 0.3, lt)))
        # dashed red route
        p = ramp(t, s0 + 1.0, s0 + 1.9) * (1 - ramp(t, lt - 0.3, lt))
        if p > 0:
            def route(d):
                for i in range(int(30 * p)):
                    y0 = 650 + i * 4.6
                    d.line((self.cx + 34 * math.sin(i / 5), y0, self.cx + 34 * math.sin((i + .55) / 5), y0 + 3), fill=(*RED, 255), width=5)
            drawn(c, route)
        # the people: microphone + radiating rings
        a = ramp(t, lt - 0.2, lt + 0.3)
        if a > 0:
            overlay(c, (14, 12, 11), (235 * a) / 255)
            def rings(d):
                for i in range(4):
                    ph = ((t - lt) * 0.9 + i / 4) % 1
                    r = 200 + ph * 420
                    d.ellipse((self.cx - r, 760 - r, self.cx + r, 760 + r), outline=(*WHITE, int(120 * a * (1 - ph))), width=3)
            drawn(c, rings)
            put(c, self.mic, self.cx, 800, scale=0.95 + 0.03 * (t - lt), alpha=a)
            label(c, "ILUSTRACIÓN", self.cx, 1215, alpha=a * 0.7)

    # -- 2: legacy (1929 debate, crowds, 1950)
    def legacy(self, c, t):
        s0, s1 = self.S["legacy"]
        c.alpha_composite(self.dark)
        k = ease_out((t - s0) / 0.45)
        crowd_t = self.L["L06"]["start"] - 0.25
        page_a = 1 - ramp(t, crowd_t - 0.2, crowd_t + 0.3)
        if page_a > 0:
            put(c, self.news2, self.cx - 10, H / 2 + (1 - k) * -900, scale=0.94 + 0.02 * (t - s0) / 4, rot=1.8, alpha=page_a)
            year = "1929"
            n = int(4 * clamp((t - s0 - 0.3) / 0.4))
            put(c, text_img(year[:n] or " ", "serif", 260, (*RED, 255), var="Black"), self.cx, 520, alpha=page_a)
            put(c, text_img("DEBATE EN EL CONGRESO", "sans", 52, (*INK, 255), tracking=4, var="Bold"),
                self.cx, 720, alpha=ramp(t, s0 + 0.9, s0 + 1.2) * page_a)
            drawn(c, lambda d: d.line((self.cx - 330, 790, self.cx + 330, 790), fill=(*INK, int(255 * page_a)), width=4))
            for i, txt in enumerate(("LA MASACRE", "DE LAS BANANERAS")):
                put(c, text_img(txt, "serif", 92, (*INK, 255), var="Black"), self.cx, 880 + i * 112,
                    alpha=ramp(t, s0 + 2.0 + 0.25 * i, s0 + 2.4 + 0.25 * i) * page_a)
            put(c, text_img("Magdalena · diciembre de 1928", "type", 38, (*INK, 255)), self.cx, 1150,
                alpha=ramp(t, s0 + 2.8, s0 + 3.2) * page_a)
        ca = ramp(t, crowd_t - 0.2, crowd_t + 0.3)
        if ca > 0:
            dt = t - crowd_t
            if self.crowd_photo:
                overlay(c, (14, 12, 11), (255 * ca) / 255)
                put(c, self.crowd_photo, self.cx + dt * 8, 840, scale=1.0 + 0.025 * dt, alpha=ca)
                label(c, "MARCHA DEL SILENCIO · BOGOTÁ, FEBRERO DE 1948", self.cx, 1235, alpha=ca)
            else:
                overlay(c, (198, 190, 174), (255 * ca) / 255)
                for i, lay in enumerate(self.crowd):
                    px = -100 - dt * (6 + 10 * i)
                    bob = 3 * math.sin(dt * (3 + i) + i)
                    put(c, lay, W / 2 + 100 + px, lay.height / 2 - 160 + bob, alpha=ca)
                label(c, "ILUSTRACIÓN", self.cx, 1215, alpha=ca, color=INK)
            pres_t = crowd_t + 1.5
            pa = ramp(t, pres_t, pres_t + 0.4) * ca
            self.kicker(c, "ELECCIONES DE 1950", 225, pa, color=WHITE if self.crowd_photo else INK)
            put(c, text_img("¿EL PRÓXIMO", "serif", 96, (*WHITE, 255), stroke=3, stroke_fill=INK, var="Black"),
                self.cx, 325, alpha=pa)
            put(c, text_img("PRESIDENTE?", "serif", 96, (*WHITE, 255), stroke=3, stroke_fill=INK, var="Black"),
                self.cx, 428, alpha=pa)

    # -- 3: assassination
    def assassination(self, c, t):
        s0, s1 = self.S["assassination"]
        R = self.rupture
        c.alpha_composite(self.dark)
        p = (t - s0) / (R - s0)
        zoom = 1.0 + 0.22 * ease(clamp(p))
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if self.portrait_big:
            put(lay, self.portrait_big, self.cx, 700 + 40 * clamp(p), scale=zoom, resample=Image.LANCZOS)
        else:
            self.name_block(lay, self.cx, 720, 1.0, scale=0.9 * zoom)
        fade_in = ramp(t, s0, s0 + 0.6)
        if t < R:
            c.alpha_composite(with_alpha(lay, fade_in))
            # darkening as the date approaches
            overlay(c, (0, 0, 0), (140 * ease(clamp(p))) / 255)
            dt0 = self.L["L07"]["start"] + 0.5
            date = "9 DE ABRIL DE 1948"
            n = int(len(date) * clamp((t - dt0) / 1.1))
            if n:
                put(c, text_img(date[:n], "type", 74, (*WHITE, 255)), self.cx, 1180)
            put(c, text_img("BOGOTÁ · CARRERA SÉPTIMA", "sans", 34, (*RED, 255), tracking=8, var="Medium"),
                self.cx, 1260, alpha=ramp(t, dt0 + 1.3, dt0 + 1.7))
        else:
            # the rupture: image torn along a jagged red line, then near-black
            q = t - R
            split = ease_out(q / 0.5) * 26
            fade = 1 - 0.7 * ease(q / 1.4)
            top_mask = Image.new("L", (W, H), 0)
            r = np.random.default_rng(3)
            pts = [(0, 0), (W, 0)]
            xs = np.linspace(W, 0, 28)
            ys = 690 + np.cumsum(r.uniform(-28, 28, 28)) * 0.6 + (xs - W / 2) * 0.18
            pts += list(zip(xs, ys))
            ImageDraw.Draw(top_mask).polygon(pts, fill=255)
            top = lay.copy()
            top.putalpha(Image.composite(lay.getchannel("A"), Image.new("L", (W, H), 0), top_mask))
            bot = lay.copy()
            inv = top_mask.point(lambda v: 255 - v)
            bot.putalpha(Image.composite(lay.getchannel("A"), Image.new("L", (W, H), 0), inv))
            gray = lambda im: with_alpha(im, fade)
            put(c, gray(top), W / 2 - split * 0.4, H / 2 - split, rot=-0.6 * split / 26)
            put(c, gray(bot), W / 2 + split * 0.4, H / 2 + split, rot=0.5 * split / 26)
            overlay(c, (0, 0, 0), (150 + 60 * ease(q / 1.4)) / 255)
            line = list(zip(xs, ys))
            drawn(c, lambda d: d.line(line, fill=(*RED, int(255 * (1 - 0.4 * ease(q / 2)))), width=5))
            m_t = self.L["L09"]["start"] - 0.1
            put(c, text_img("†", "serif", 120, (*WHITE, 255), var="Regular"), self.cx, 1080, alpha=ramp(t, m_t, m_t + 0.5))
            put(c, text_img("9 · IV · 1948", "serif", 70, (*WHITE, 255), tracking=6, var="Regular"),
                self.cx, 1190, alpha=ramp(t, m_t + 0.2, m_t + 0.7))
        out = ramp(t, s1 - 0.35, s1)
        if out > 0:
            overlay(c, (0, 0, 0), (255 * out) / 255)

    # -- 4: bogotazo
    def bogotazo(self, c, t):
        s0, s1 = self.S["bogotazo"]
        dt = t - s0
        c.alpha_composite(paper_black())
        hit = 1 - ease(dt / 0.35)
        if self.tram_photo:
            c.alpha_composite(fire_layer(t, 1150, 900, 0.7))
            put(c, self.tram_photo, self.cx, 760 + hit * 18, scale=1.04 + 0.03 * dt)
            c.alpha_composite(with_alpha(fire_layer(t * 1.3, 1250, 500, 0.6), 0.35))
            label(c, "TRANVÍA EN LLAMAS · BOGOTÁ, 9 DE ABRIL DE 1948", self.cx, 1215)
        else:
            c.alpha_composite(fire_layer(t, 1150, 760, 1.0))
            put(c, self.city, W / 2 - dt * 14, 1150 - 450 + hit * 18, scale=1.0 + 0.01 * dt)
            c.alpha_composite(GROUND)
            label(c, "ILUSTRACIÓN", self.cx, 1215)
        self.embers.draw(c, t, ramp(t, s0, s0 + 0.6))
        put(c, text_img("EL BOGOTAZO", "serif", 132, (*WHITE, 255), stroke=2, stroke_fill=INK, var="Black"),
            self.cx, 300, scale=1.0 + 0.08 * hit, alpha=ramp(t, s0 + 0.05, s0 + 0.3))
        if hit > 0:
            overlay(c, (255, 240, 220), (70 * hit ** 2) / 255)
        out = ramp(t, s1 - 0.4, s1)
        if out > 0:
            overlay(c, (0, 0, 0), (255 * out) / 255)

    # -- 5: title card
    def title(self, c, t):
        s0, s1 = self.S["title"]
        overlay(c, (6, 5, 5), 1.0)
        a = ramp(t, s0 + 0.1, s0 + 0.8) * (1 - ramp(t, s1 - 0.5, s1))
        put(c, text_img("JORGE ELIÉCER", "serif", 84, (*WHITE, 255), tracking=4, var="Black"), self.cx, 780, alpha=a)
        put(c, text_img("GAITÁN", "serif", 190, (*WHITE, 255), tracking=8, var="Black"), self.cx, 920, alpha=a)
        w = 260 * ease((t - s0 - 0.4) / 0.8)
        if w > 1:
            drawn(c, lambda d: d.line((self.cx - w, 1040, self.cx + w, 1040), fill=(*RED, int(255 * a)), width=4))
        put(c, text_img("EL HOMBRE QUE PUDO CAMBIAR COLOMBIA", "sans", 36, (*WHITE, 255), tracking=5, var="Regular"),
            self.cx, 1100, alpha=ramp(t, s0 + 0.6, s0 + 1.2) * (1 - ramp(t, s1 - 0.5, s1)))
        put(c, text_img("† BOGOTÁ, 9 DE ABRIL DE 1948", "sans", 30, (*RED, 255), tracking=6, var="Regular"),
            self.cx, 1160, alpha=ramp(t, s0 + 0.8, s0 + 1.4) * (1 - ramp(t, s1 - 0.5, s1)))

    def frame(self, t):
        c = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        for name in ("hook", "rise", "legacy", "assassination", "bogotazo", "title"):
            a, b = self.S[name]
            if a <= t < b or (name == "title" and t >= a):
                getattr(self, name)(c, t)
                break
        return c


GROUND = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(GROUND).rectangle((0, 1148, W, H), fill=(8, 7, 7, 255))


@lru_cache(None)
def paper_black():
    return paper_texture((10, 8, 8), dark=True, seed=9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=float, nargs="*", help="only write still frames at these times")
    ap.add_argument("--out", default=str(OUT / "gaitan_tiktok_1080x1920.mp4"))
    args = ap.parse_args()
    tl = json.loads((ROOT / "production" / "timeline.json").read_text())
    timing = json.loads((OUT / "narration_timing.json").read_text())
    sc = Scenes(tl, timing)
    film = Film()
    chunks = [(a, min(b, tl["sections"]["title"][0]), x) for a, b, x in subtitle_chunks(timing["lines"])]
    (OUT / "subtitles.srt").write_text(srt(chunks), encoding="utf-8")
    print("fallback plates:", sc.used_fallback)

    def render(f):
        t = f / FPS
        c = sc.frame(t)
        img = film.apply(c, f, t)
        img = img.convert("RGBA")
        draw_subs(img, t, chunks)
        return img.convert("RGB")

    if args.preview is not None:
        (OUT / "preview").mkdir(exist_ok=True)
        for t in args.preview:
            render(int(t * FPS)).save(OUT / "preview" / f"f_{t:05.2f}.jpg", quality=88)
        return

    n = int(tl["duration"] * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(OUT / "mix.wav"),
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-maxrate", "12M", "-bufsize", "24M",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1", "-tune", "film",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart",
           "-t", str(tl["duration"]), "-metadata", "title=Jorge Eliécer Gaitán — el hombre que pudo cambiar Colombia",
           args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n):
        proc.stdin.write(render(f).tobytes())
        if f % 90 == 0:
            print(f"frame {f}/{n}", flush=True)
    proc.stdin.close()
    proc.wait()
    print("wrote", args.out)


def srt(chunks):
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{chr(10).join(wrap(t))}\n" for i, (a, b, t) in enumerate(chunks, 1))


if __name__ == "__main__":
    main()
