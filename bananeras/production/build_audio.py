#!/usr/bin/env python3
"""Narration, original score, sound design and final mix for *La Masacre de las Bananeras*.

Narration: assets/audio/narration/<LINE_ID>.wav is used when present (professional take,
one file per line). Otherwise a scratch voice is synthesized with Piper (es-carlfm-x-low,
phonemized with espeak's Latin-American Spanish rules: seseo and yeísmo).

Outputs (out/): narration.wav, music.wav, sfx.wav, mix.wav (48 kHz stereo, -14 LUFS)
and narration_timing.json (measured line times + derived section/cue times for the renderer).
"""
import json
import subprocess
import tarfile
import urllib.request
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
VOICES = ROOT / "assets" / "voices"
VOICE_URL = "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-es-carlfm-x-low.tar.gz"
rng = np.random.default_rng(1928)


# ---------------------------------------------------------------- dsp helpers
def read_wav(path):
    sr, x = wavfile.read(path)
    if x.dtype == np.int16:
        x = x.astype(np.float32) / 32768.0
    elif x.dtype == np.int32:
        x = x.astype(np.float32) / 2147483648.0
    x = x.astype(np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return resample(x, sr)


def resample(x, sr):
    if sr == SR:
        return x
    g = np.gcd(sr, SR)
    return signal.resample_poly(x, SR // g, sr // g).astype(np.float32)


def write_wav(path, x):
    x = np.clip(x, -1.0, 1.0)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    wavfile.write(path, SR, (x * 32767).astype(np.int16))


def db(v):
    return 10 ** (v / 20)


def env_adsr(n, a, d, s, r):
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    sus = max(n - a - d - r, 0)
    e = np.concatenate([np.linspace(0, 1, max(a, 1)) ** 2, np.linspace(1, s, max(d, 1)),
                        np.full(sus, s), np.linspace(s, 0, max(r, 1)) ** 1.5])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def bp(x, lo, hi, order=2):
    return signal.sosfilt(signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x)


def lp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def place(buf, clip, t, gain=1.0, pan=0.0):
    """Add a mono clip into a stereo buffer at time t with equal-power pan (-1..1)."""
    i = int(t * SR)
    if i >= len(buf) or i < 0:
        return
    clip = clip[: len(buf) - i]
    th = (pan + 1) * np.pi / 4
    buf[i:i + len(clip), 0] += clip * gain * np.cos(th)
    buf[i:i + len(clip), 1] += clip * gain * np.sin(th)


def reverb(x, wet=0.3, seconds=2.6, damp=3.0):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    y = np.zeros_like(x)
    for c in range(2):
        ir = lp(rng.standard_normal(n), 5000) * np.exp(-damp * t)
        ir[: int(0.015 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        y[:, c] = signal.fftconvolve(x[:, c], ir)[: len(x)]
    return x * (1 - wet) + y * wet


def fade(x, fin=0.0, fout=0.0):
    n = len(x)
    g = np.ones(n)
    a, b = int(fin * SR), int(fout * SR)
    if a:
        g[:a] = np.linspace(0, 1, a) ** 2
    if b:
        g[n - b:] = np.linspace(1, 0, b) ** 2
    return x * g


# ---------------------------------------------------------------- instruments
def bowed(freq, dur, amp=0.2, attack=0.8, release=1.2, bright=0.6, vib=0.004):
    """Low string section: detuned additive saw with vibrato."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for det in (-0.006, 0.0, 0.0045):
        f = freq * (1 + det) * (1 + vib * np.sin(2 * np.pi * (5.1 + det * 40) * t + rng.uniform(0, 6)))
        ph = 2 * np.pi * np.cumsum(f) / SR
        for h in range(1, 14):
            if freq * h > 9000:
                break
            out += np.sin(h * ph) * (1.0 / h) * (bright ** (h - 1) * 0.6 + 0.4 * (h == 1))
    out = lp(out, min(1800 + freq * 6, 9000))
    return out * env_adsr(n, attack, 0.3, 0.85, release) * amp / 3


def brass(freq, dur, amp=0.15, attack=0.5, release=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    e = env_adsr(n, attack, 0.4, 0.8, release)
    ph = 2 * np.pi * freq * t + 0.002 * np.sin(2 * np.pi * 4.7 * t)
    out = np.zeros(n)
    for h in range(1, 18):
        if freq * h > 8000:
            break
        out += np.sin(h * ph) / h * e ** (0.6 + 0.35 * h)
    return lp(out, 2600) * amp


def timpani(freq=73.4, amp=0.5, decay=1.6):
    n = int((decay * 2.2) * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 0.05 * np.exp(-t * 18))
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = (np.sin(ph) + 0.5 * np.sin(1.504 * ph) + 0.28 * np.sin(1.742 * ph) + 0.18 * np.sin(2.0 * ph))
    body *= np.exp(-t / decay * 2.2)
    mallet = lp(rng.standard_normal(n), 900) * np.exp(-t * 60) * 0.6
    return (body + mallet) * amp / 1.6


def tambora(amp=0.3, muted=True):
    """Colombian Caribbean bass drum: pitched skin thump (+ rim 'golpe' when not muted)."""
    n = int(0.6 * SR)
    t = np.arange(n) / SR
    f = 92 * (1 + 0.6 * np.exp(-t * 30))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (14 if muted else 7))
    skin = bp(rng.standard_normal(n), 200, 900) * np.exp(-t * 45) * 0.25
    return (body + skin) * amp


def guache(amp=0.06, length=0.11):
    """Shaker stroke (guache / maracas): band-passed noise with a swelling-then-dying envelope."""
    n = int(length * SR)
    t = np.arange(n) / SR
    e = (t / length) ** 0.4 * np.exp(-t * 38)
    return hp(bp(rng.standard_normal(n), 3500, 11000), 2500) * e * amp


def gaita(freq, dur, amp=0.07):
    """Breathy cane flute (gaita) voice: sine + octave partial + breath noise, slow vibrato."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 0.006 * np.sin(2 * np.pi * 4.6 * t) * np.clip(t / 0.5, 0, 1))
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.06 * np.sin(3 * ph)
    breath = bp(rng.standard_normal(n), freq * 0.9, freq * 3.5) * 0.35
    return (tone + breath) * env_adsr(n, 0.12, 0.2, 0.8, min(0.5, dur * 0.4)) * amp


def snare_soft(amp=0.12):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    wires = bp(rng.standard_normal(n), 1500, 7000) * np.exp(-t * 22)
    shell = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 35) * 0.5
    return lp(wires + shell, 3500) * amp  # muffled, far away


def impact(amp=0.9, f0=58, f1=32, length=3.0, noise=0.4):
    n = int(length * SR)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t * 6)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6)
    nz = lp(rng.standard_normal(n), 400) * np.exp(-t * 7) * noise
    click = hp(rng.standard_normal(n), 1500) * np.exp(-t * 90) * 0.15
    return (s + nz + click) * amp


def paper(length=0.45, amp=0.25):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = bp(rng.standard_normal(n), 900, 7000)
    flutter = np.abs(lp(rng.standard_normal(n), 40))
    flutter /= flutter.max() + 1e-9
    return x * flutter * np.sin(np.pi * t / length) ** 0.7 * amp


def stamp(amp=0.5):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    wood = np.sin(2 * np.pi * 160 * t) * np.exp(-t * 40) + 0.5 * np.sin(2 * np.pi * 410 * t) * np.exp(-t * 60)
    slap = bp(rng.standard_normal(n), 400, 4000) * np.exp(-t * 80)
    return (wood + slap) * amp


def boot(amp=0.2):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    heel = np.sin(2 * np.pi * rng.uniform(70, 85) * t) * np.exp(-t * 30)
    grit = bp(rng.standard_normal(n), 800, 5000) * np.exp(-t * 25) * 0.35
    return (heel + grit) * amp


def press_clack(amp=0.15):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    metal = bp(rng.standard_normal(n), 1200, 6000) * np.exp(-t * 70)
    thunk = np.sin(2 * np.pi * 120 * t) * np.exp(-t * 40)
    return (metal * 0.7 + thunk) * amp


def rail_ambience(length):
    """Distant freight train: low rumble, rail-joint double clacks, steam hiss, insects, leaves."""
    n = int(length * SR)
    t = np.arange(n) / SR
    out = lp(rng.standard_normal(n), 140) * 0.5
    k = 0.25
    while k < length - 0.3:  # clack-clack every ~0.85 s
        for off in (0.0, 0.13):
            i = int((k + off) * SR)
            L = int(0.09 * SR)
            tt = np.arange(L) / SR
            out[i:i + L] += bp(rng.standard_normal(L), 400, 2500) * np.exp(-tt * 55) * 1.1
        k += 0.85
    hiss = hp(rng.standard_normal(n), 3000) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.35 * t) ** 2) * 0.12
    insects = bp(rng.standard_normal(n), 5200, 7200) * (0.6 + 0.4 * np.sin(2 * np.pi * 7 * t)) * 0.10
    leaves = bp(rng.standard_normal(n), 600, 3000) * np.abs(lp(rng.standard_normal(n), 1.5)) * 2.0
    x = out + hiss + insects + leaves * 0.25
    return x / (np.abs(x).max() + 1e-9)


def wind(length, amp=0.1):
    n = int(length * SR)
    x = bp(rng.standard_normal(n), 250, 1400)
    m = np.abs(lp(rng.standard_normal(n), 0.8))
    x *= m / (m.max() + 1e-9)
    return x / (np.abs(x).max() + 1e-9) * amp


NOTE = {"D1": 36.71, "A1": 55.0, "C2": 65.41, "D2": 73.42, "E2": 82.41, "F2": 87.31, "G2": 98.0,
        "A2": 110.0, "Bb2": 116.54, "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61,
        "G3": 196.0, "A3": 220.0, "Bb3": 233.08, "C4": 261.63, "C#4": 277.18, "D4": 293.66,
        "E4": 329.63, "F4": 349.23, "G4": 392.0, "A4": 440.0, "Bb4": 466.16, "C5": 523.25, "D5": 587.33}


# ---------------------------------------------------------------- timing
def word_time(line, word):
    """Approximate time a word is spoken (character share of the line; no forced alignment)."""
    txt = line["sub"].replace("| ", "")
    return round(line["start"] + (line["end"] - line["start"]) * txt.index(word) / len(txt), 3)


def section_times(lines, T):
    """Section boundaries and cue times derived from measured narration."""
    L = {l["id"]: l for l in lines}
    rupture = L["L3b"]["end"] + 0.18
    return {
        "setting": [0.0, L["L2"]["start"] - 0.35],
        "strike": [L["L2"]["start"] - 0.35, L["L3a"]["start"] - 0.35],
        "army": [L["L3a"]["start"] - 0.35, rupture],
        "after": [rupture, L["L5"]["start"] - 0.45],
        "gaitan": [L["L5"]["start"] - 0.45, L["L6"]["start"] - 0.4],
        "lesson": [L["L6"]["start"] - 0.4, T],
        "rupture": rupture,
        "final_card": L["L7"]["start"] - 0.25,
        "sting": L["L7"]["end"] + 0.05,
        "file": word_time(L["L5"], "investigó") - 0.2,
        "congreso": word_time(L["L5"], "Congreso"),
        "country": word_time(L["L5"], "ante todo") - 0.1,
    }


# ---------------------------------------------------------------- score
def build_score(T, S):
    buf = np.zeros((int(T * SR), 2))
    beat = 60 / 80
    s0, s1 = S["setting"]
    k0, k1 = S["strike"]
    a0 = S["army"][0]
    R = S["rupture"]
    g0, g1 = S["gaitan"]
    l0 = S["lesson"][0]

    # --- setting + strike: low D-minor strings, muted cumbia pulse (tambora + guache), lone gaita
    prog = [("D2", "F3"), ("Bb2", "D3"), ("G2", "Bb3"), ("A2", "C#4")]
    t, bar = s0, 0
    while t < a0 - 0.1:
        root, third = prog[bar % 4]
        dur = beat * 4
        place(buf, bowed(NOTE[root], dur * 1.05, 0.19, attack=0.6 if bar == 0 else 0.3, release=0.6), t, pan=-0.25)
        place(buf, bowed(NOTE[third], dur * 1.05, 0.06, attack=0.6, release=0.7), t, pan=0.3)
        intensity = 0.55 if t < k0 else 0.85
        for b in range(4):
            tb = t + b * beat
            if tb >= a0 - 0.1:
                break
            if b in (0, 2):
                place(buf, tambora(0.22 * intensity), tb, pan=-0.1)
            if b == 3:
                place(buf, tambora(0.12 * intensity), tb + beat / 2, pan=-0.1)
            for e8 in range(2):  # guache on eighths, accent on the off-beat (cumbia lilt)
                place(buf, guache(0.05 * intensity * (1.3 if e8 else 0.8)), tb + e8 * beat / 2, pan=0.35)
        t += dur
        bar += 1
    # gaita lament motif in the opening (D minor, descending) and an echo in the strike
    def motif(notes, t, amp):
        for nt, d in notes:
            place(buf, gaita(NOTE[nt], d + 0.15, amp), t, pan=0.2)
            t += d
    motif([("A4", 0.55), ("G4", 0.35), ("F4", 0.35), ("E4", 0.5), ("D4", 1.3)], s0 + 1.2, 0.055)
    motif([("D5", 0.4), ("C5", 0.4), ("A4", 0.9)], k0 + 2.0, 0.035)

    # --- army: march pulse, muffled snare, rising string cluster, all cut dead at the rupture
    span = R - a0
    place(buf, bowed(NOTE["D2"], span + 0.05, 0.22, attack=0.5, release=0.04, bright=0.4), a0)
    place(buf, bowed(NOTE["D1"], span + 0.05, 0.16, attack=1.0, release=0.04, bright=0.3), a0)
    place(buf, bowed(NOTE["A3"], span - 0.6, 0.035, attack=2.5, release=0.04, vib=0.007), a0 + 0.6, pan=0.3)
    place(buf, bowed(NOTE["Bb3"], span - 2.0, 0.03, attack=2.5, release=0.04, vib=0.008), a0 + 2.0, pan=-0.3)
    tt, k = a0, 0
    while tt < R - 0.25:
        prog_amp = 0.5 + 0.5 * (tt - a0) / span
        place(buf, timpani(NOTE["D2"] / 2, 0.24 * prog_amp, decay=0.45), tt)
        place(buf, snare_soft(0.10 * prog_amp), tt + beat / 2, pan=0.15)
        if k % 2:
            place(buf, snare_soft(0.06 * prog_amp), tt + beat * 0.75, pan=0.15)
        tt += beat
        k += 1
    buf[int(R * SR):] = 0.0  # everything stops dead at the rupture

    # --- after: near silence, then one thin high tone and a slow, low lament
    place(buf, bowed(NOTE["A4"], 4.5, 0.018, attack=1.8, release=2.0, bright=0.25, vib=0.003), R + 0.9, pan=0.15)
    place(buf, bowed(NOTE["D3"], g0 - R - 2.0, 0.05, attack=1.6, release=1.5, bright=0.3), R + 2.4, pan=-0.2)
    place(buf, bowed(NOTE["F3"], g0 - R - 3.0, 0.03, attack=1.6, release=1.5, bright=0.3), R + 3.4, pan=0.25)
    motif([("D4", 0.8), ("F4", 0.6), ("E4", 0.6), ("D4", 1.6)], R + 3.2, 0.03)

    # --- gaitan: gradual emotional build (strings climb, timpani pulse, brass swell)
    climb = [("D2", "A2", "F3"), ("Bb2", "F3", "D4"), ("G2", "D3", "Bb3"), ("A2", "E3", "C#4")]
    t, i = g0, 0
    while t < l0 - 0.1:
        lo, mid, hi = climb[i % 4]
        d = min(beat * 4, l0 - t + 0.4)
        g = 0.6 + 0.4 * (t - g0) / max(l0 - g0, 1)
        place(buf, bowed(NOTE[lo], d * 1.05, 0.2 * g, attack=0.4, release=0.6), t, pan=-0.25)
        place(buf, bowed(NOTE[mid], d * 1.05, 0.09 * g, attack=0.5, release=0.6), t, pan=0.2)
        place(buf, bowed(NOTE[hi], d * 1.05, 0.05 * g, attack=0.8, release=0.6), t, pan=0.35)
        place(buf, timpani(NOTE["D2"] if NOTE[lo] < 100 else NOTE[lo] / 2, 0.18 * g), t)
        place(buf, tambora(0.12 * g, muted=False), t + beat * 2)
        t += beat * 4
        i += 1
    place(buf, brass(NOTE["D3"], 3.4, 0.08, attack=1.6, release=1.2), l0 - 3.0, pan=-0.15)
    place(buf, brass(NOTE["A3"], 3.2, 0.05, attack=1.8, release=1.2), l0 - 2.8, pan=0.2)

    # --- lesson: thin out to one held chord; final sting on the last words
    place(buf, bowed(NOTE["D2"], S["sting"] - l0 + 0.3, 0.16, attack=0.6, release=0.6, bright=0.4), l0)
    place(buf, bowed(NOTE["F3"], S["sting"] - l0, 0.05, attack=1.0, release=0.6), l0 + 0.3, pan=0.25)
    place(buf, bowed(NOTE["A3"], S["sting"] - l0 - 0.8, 0.035, attack=1.2, release=0.6), l0 + 0.9, pan=-0.25)
    st = S["sting"]
    for nt, gg, pn in (("D1", 0.18, 0), ("D2", 0.22, -0.25), ("A2", 0.12, 0.25), ("D3", 0.09, -0.1), ("F3", 0.05, 0.3)):
        place(buf, bowed(NOTE[nt], 2.6, gg, attack=0.04, release=2.0, bright=0.45), st, pan=pn)
    place(buf, brass(NOTE["D3"], 2.2, 0.12, attack=0.05, release=1.8), st, pan=-0.1)
    place(buf, brass(NOTE["A3"], 2.0, 0.07, attack=0.06, release=1.7), st, pan=0.15)
    place(buf, timpani(NOTE["D2"], 0.4, decay=1.8), st)
    return reverb(buf, wet=0.3)


def build_sfx(T, S, lines):
    buf = np.zeros((int(T * SR), 2))
    L = {l["id"]: l for l in lines}
    s1 = S["setting"][1]
    k0, k1 = S["strike"]
    a0 = S["army"][0]
    R = S["rupture"]
    g0, g1 = S["gaitan"]

    # setting: plantation + railway ambience, fading under the strike
    amb = rail_ambience(s1 + 1.5)
    place(buf, fade(amb, 0.6, 1.5) * 0.30, 0.0, pan=-0.2)
    # strike: documents slide in, the petition is stamped
    for t in (k0 + 0.15, k0 + 1.3, k0 + 2.6, k0 + 3.8):
        place(buf, paper(0.45, 0.22), t, pan=rng.uniform(-0.4, 0.4))
    place(buf, stamp(0.42), k1 - 1.0, pan=0.1)
    # army: measured boots, approaching
    beat = 60 / 80
    t = a0 + 0.2
    while t < R - 0.15:
        g = 0.25 + 0.75 * (t - a0) / (R - a0)
        for off in (0.0, beat / 2):
            place(buf, boot(0.18 * g), t + off + rng.uniform(-0.01, 0.01), pan=(-0.3 if off else 0.3) * (1 - g))
        t += beat
    buf[int(R * SR):] = 0.0
    # rupture: one restrained accent — a muffled low thud and a single dry crack, then silence
    place(buf, lp(impact(0.7, 48, 26, 2.8, noise=0.5), 260), R)
    crack = hp(rng.standard_normal(int(0.03 * SR)), 900) * np.exp(-np.arange(int(0.03 * SR)) / SR * 160)
    place(buf, lp(crack, 3200) * 0.35, R)
    # after: wind across an empty square, scattered papers
    place(buf, fade(wind(S["after"][1] - R - 0.8, 0.09), 1.2, 1.5), R + 0.8)
    for t in (R + 1.4, R + 2.3, R + 4.6):
        place(buf, paper(0.6, 0.10), t, pan=rng.uniform(-0.6, 0.6))
    # newspaper press under the investigation
    t = g0 + 0.3
    while t < g1 - 0.4:
        place(buf, press_clack(0.10), t, pan=0.2)
        place(buf, press_clack(0.05), t + 0.25, pan=0.25)
        t += 0.5
    for t in (g0 + 0.05, g0 + 2.2):
        place(buf, paper(0.5, 0.18), t, pan=-0.2)
    place(buf, stamp(0.35), S["congreso"], pan=0.05)
    # lesson: newspaper folds into darkness before the last card
    place(buf, paper(0.7, 0.16), S["final_card"] - 0.35, pan=0.0)
    return reverb(buf, wet=0.15)


# ---------------------------------------------------------------- narration
def scratch_voice(tl):
    from piper import PiperVoice
    from piper.config import SynthesisConfig
    v = tl["voice"]
    model = VOICES / v["model"]
    if not model.exists():
        VOICES.mkdir(parents=True, exist_ok=True)
        tgz = VOICES / "voice.tar.gz"
        urllib.request.urlretrieve(VOICE_URL, tgz)
        with tarfile.open(tgz) as tf:
            tf.extractall(VOICES / model.parent.name, filter="data")
        tgz.unlink()
    pv = PiperVoice.load(str(model))
    pv.config.espeak_voice = v["espeak"]  # Latin-American Spanish: seseo, yeísmo
    cfg = SynthesisConfig(length_scale=v["length_scale"], noise_scale=v["noise_scale"],
                          noise_w_scale=v["noise_w_scale"])

    def synth(text):
        a = np.concatenate([c.audio_float_array for c in pv.synthesize(text, cfg)])
        return resample(a.astype(np.float32), pv.config.sample_rate)
    return synth


def trim_silence(x, thresh=0.012):
    a = signal.convolve(np.abs(x), np.ones(240) / 240, mode="same")
    idx = np.where(a > thresh)[0]
    if len(idx) == 0:
        return x
    return x[max(idx[0] - 240, 0): min(idx[-1] + 1200, len(x))]


def process_voice(x):
    x = hp(x, 80, order=2)
    x = x + 0.22 * bp(x, 2200, 4800) - 0.15 * bp(x, 220, 420)  # presence up, mud down
    win = int(0.02 * SR)  # ~3:1 RMS compression above -20 dBFS
    rms = np.sqrt(signal.convolve(x ** 2, np.ones(win) / win, mode="same") + 1e-9)
    thr = db(-20)
    gain = np.where(rms > thr, (thr * (rms / thr) ** (1 / 3)) / rms, 1.0)
    x = x * signal.convolve(gain, np.ones(win) / win, mode="same")
    return x / (np.abs(x).max() + 1e-9) * db(-3)


def build_narration(tl):
    ndir = ROOT / "assets" / "audio" / "narration"
    synth, clips, source = None, [], "professional"
    for ln in tl["lines"]:
        f = ndir / f"{ln['id']}.wav"
        if f.exists():
            x = read_wav(f)
        else:
            source = "scratch (Piper es-carlfm-x-low, es-419 phonemes)"
            synth = synth or scratch_voice(tl)
            x = synth(ln.get("tts", ln["sub"].replace("| ", "")))
        clips.append(process_voice(trim_silence(x)))
    timing, prev = [], 0.0
    for ln, x in zip(tl["lines"], clips):
        start = max(ln["at"], prev + 0.3)
        timing.append({"id": ln["id"], "start": round(start, 3), "end": round(start + len(x) / SR, 3), "sub": ln["sub"]})

        prev = start + len(x) / SR
    T = round(prev + tl["tail"], 2)
    buf = np.zeros(int(T * SR))
    for tm, x in zip(timing, clips):
        i = int(tm["start"] * SR)
        buf[i:i + len(x)] += x
    return buf, timing, source, T


def duck(music, voice, depth_db=-9, attack=0.08, release=0.5):
    env = signal.convolve(np.abs(voice), np.ones(int(0.03 * SR)) / int(0.03 * SR), mode="same")
    target = 1 - (env > db(-38)).astype(float) * (1 - db(depth_db))
    # one-pole smoothing, decimated for speed
    step = 48
    tg = target[::step]
    g = np.empty_like(tg)
    cur = 1.0
    a, r = min(1, step / (attack * SR) * 4), min(1, step / (release * SR) * 4)
    for i, v in enumerate(tg):
        cur += (v - cur) * (a if v < cur else r)
        g[i] = cur
    g = np.repeat(g, step)[: len(target)]
    return music * g[:, None]


def main():
    tl = json.loads((ROOT / "production" / "timeline.json").read_text())
    OUT.mkdir(exist_ok=True)
    voice, timing, vsource, T = build_narration(tl)
    S = section_times(timing, T)

    mfile = ROOT / "assets" / "audio" / "music.wav"
    if mfile.exists():
        m = read_wav(mfile)[: int(T * SR)]
        music = np.pad(np.stack([m, m], axis=1), ((0, int(T * SR) - len(m)), (0, 0)))
        msource = "external"
    else:
        music, msource = build_score(T, S), "synthesized"
    sfx = build_sfx(T, S, timing)

    music = hp(music.T, 45, order=4).T  # phone speakers: no sub rumble, mids lifted
    if msource == "synthesized":
        music = music + 1.4 * bp(music.T, 280, 2200).T
    sfx = hp(sfx.T, 35, order=4).T
    music = music / (np.abs(music).max() + 1e-9) * db(-6)
    sfx = sfx / (np.abs(sfx).max() + 1e-9) * db(-8)
    if tl.get("narration_in_mix", True):
        mix = np.stack([voice, voice], axis=1) + duck(music, voice) * db(-5) + sfx * db(-5)
    else:  # narration still times subtitles, sections and cues, but is not heard
        mix = music * db(-5) + sfx * db(-5)
    n = len(mix)
    mix[n - int(0.5 * SR):] *= (np.linspace(1, 0, int(0.5 * SR)) ** 2)[:, None]
    mix = mix / (np.abs(mix).max() + 1e-9) * db(-1.5)

    write_wav(OUT / "narration.wav", voice)
    write_wav(OUT / "music.wav", music)
    write_wav(OUT / "sfx.wav", sfx)
    write_wav(OUT / "mix_premaster.wav", mix)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT / "mix_premaster.wav"),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "2",
                    str(OUT / "mix.wav")], check=True)
    meta = {"duration": T, "narration_source": vsource, "narration_in_mix": tl.get("narration_in_mix", True), "music_source": msource,
            "sections": S, "lines": timing}
    (OUT / "narration_timing.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
