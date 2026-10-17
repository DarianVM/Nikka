#!/usr/bin/env python3
"""Build narration, original score, sound design and the final mix.

Inputs (all optional, fall back to generated material):
  assets/audio/narration/<LINE_ID>.wav   professional narration, one file per line
  assets/audio/music.wav                 licensed / generated score (replaces synth score)

Outputs (out/):
  narration.wav, music.wav, sfx.wav, mix_premaster.wav, mix.wav (48 kHz stereo)
  narration_timing.json  actual start/end of every narration line (drives subtitles)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
rng = np.random.default_rng(1948)


# ---------------------------------------------------------------- helpers
def read_wav(path):
    sr, x = wavfile.read(path)
    if x.dtype == np.int16:
        x = x.astype(np.float32) / 32768.0
    elif x.dtype == np.int32:
        x = x.astype(np.float32) / 2147483648.0
    x = x.astype(np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if sr != SR:
        g = np.gcd(sr, SR)
        x = signal.resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def write_wav(path, x):
    x = np.clip(x, -1.0, 1.0)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    wavfile.write(path, SR, (x * 32767).astype(np.int16))


def env_adsr(n, a, d, s, r, sr=SR):
    a, d, r = int(a * sr), int(d * sr), int(r * sr)
    sus = max(n - a - d - r, 0)
    e = np.concatenate([
        np.linspace(0, 1, max(a, 1)) ** 2,
        np.linspace(1, s, max(d, 1)),
        np.full(sus, s),
        np.linspace(s, 0, max(r, 1)) ** 1.5,
    ])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def bp(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def lp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def place(buf, clip, t, gain=1.0, pan=0.0):
    """Add mono clip into stereo buffer at time t with equal-power pan (-1..1)."""
    i = int(t * SR)
    if i >= len(buf):
        return
    clip = clip[: len(buf) - i]
    th = (pan + 1) * np.pi / 4
    buf[i:i + len(clip), 0] += clip * gain * np.cos(th)
    buf[i:i + len(clip), 1] += clip * gain * np.sin(th)


def make_ir(seconds=2.6, damp=3.2):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = np.zeros((n, 2))
    for c in range(2):
        noise = rng.standard_normal(n)
        noise = lp(noise, 5200)
        ir[:, c] = noise * np.exp(-damp * t)
    ir[: int(0.012 * SR)] = 0  # pre-delay
    return ir / np.sqrt((ir ** 2).sum(axis=0, keepdims=True))


IR = None


def reverb(x, wet=0.3, seconds=2.6):
    global IR
    if IR is None:
        IR = make_ir(seconds)
    y = np.zeros_like(x)
    for c in range(2):
        y[:, c] = signal.fftconvolve(x[:, c], IR[:, c])[: len(x)]
    return x * (1 - wet) + y * wet


def db(v):
    return 10 ** (v / 20)


# ---------------------------------------------------------------- instruments
def bowed(freq, dur, amp=0.2, attack=0.8, release=1.2, bright=0.6, vib=0.004):
    """Ensemble low strings / cello section: detuned additive saw with vibrato."""
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


def pluck(freq, dur=1.6, amp=0.12, damping=0.996):
    """Karplus-Strong; doubled at the octave like a tiple course."""
    n = int(dur * SR)
    out = np.zeros(n)
    for mult, g in ((1.0, 1.0), (2.003, 0.55)):
        p = int(SR / (freq * mult))
        buf = rng.uniform(-1, 1, p)
        buf = lp(buf, 4000)
        y = np.zeros(n)
        for i in range(n):
            y[i] = buf[i % p]
            buf[i % p] = damping * 0.5 * (buf[i % p] + buf[(i + 1) % p])
        out += y * g
    out = hp(out, 120)
    return out * np.exp(-np.arange(n) / SR * 1.6) * amp


def impact(amp=0.9, f0=58, f1=32, length=3.0, noise=0.4):
    n = int(length * SR)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t * 6)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6)
    nz = lp(rng.standard_normal(n), 400) * np.exp(-t * 7) * noise
    click = hp(rng.standard_normal(n), 1500) * np.exp(-t * 90) * 0.15
    return (s + nz + click) * amp


def typewriter_key():
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    k = bp(rng.standard_normal(n), 1800, 6000) * np.exp(-t * 160)
    thunk = np.sin(2 * np.pi * rng.uniform(140, 190) * t) * np.exp(-t * 70) * 0.5
    return (k * 0.8 + thunk) * rng.uniform(0.6, 1.0)


def paper(length=0.45, amp=0.25):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = bp(rng.standard_normal(n), 900, 7000)
    flutter = np.abs(lp(rng.standard_normal(n), 40))
    flutter /= flutter.max() + 1e-9
    e = np.sin(np.pi * t / length) ** 0.7
    return x * flutter * e * amp


def crowd(length, amp=0.1):
    n = int(length * SR)
    out = np.zeros((n, 2))
    for v in range(28):
        f = rng.uniform(250, 1400)
        voice = bp(rng.standard_normal(n), f * 0.7, f * 1.6)
        rate = rng.uniform(2.5, 6.0)
        syl = np.clip(lp(rng.standard_normal(n), rate), 0, None)
        syl /= syl.max() + 1e-9
        pan = rng.uniform(-0.9, 0.9)
        th = (pan + 1) * np.pi / 4
        out[:, 0] += voice * syl * np.cos(th)
        out[:, 1] += voice * syl * np.sin(th)
    out = lp(out.T, 2200).T  # distant
    out /= np.abs(out).max() + 1e-9
    return out * amp


def fire(length, amp=0.12):
    n = int(length * SR)
    out = lp(rng.standard_normal(n), 300) * 0.5
    for _ in range(int(length * 38)):
        i = rng.integers(0, n - 2000)
        L = rng.integers(200, 1800)
        tt = np.arange(L) / SR
        out[i:i + L] += hp(rng.standard_normal(L), 2000) * np.exp(-tt * rng.uniform(200, 600)) * rng.uniform(0.3, 1.5)
    return out / (np.abs(out).max() + 1e-9) * amp


def projector(length, amp=0.03):
    n = int(length * SR)
    t = np.arange(n) / SR
    hum = lp(rng.standard_normal(n), 900)
    shutter = 0.6 + 0.4 * (np.sin(2 * np.pi * 24 * t) > 0.7)
    motor = 0.3 * np.sin(2 * np.pi * 50 * t)
    x = hum * shutter + motor * 0.2
    return x / (np.abs(x).max() + 1e-9) * amp


# ---------------------------------------------------------------- score
NOTE = {"D1": 36.71, "A1": 55.0, "D2": 73.42, "E2": 82.41, "F2": 87.31, "G2": 98.0, "A2": 110.0,
        "Bb2": 116.54, "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0,
        "A3": 220.0, "Bb3": 233.08, "C4": 261.63, "C#4": 277.18, "D4": 293.66, "E4": 329.63,
        "F4": 349.23, "A4": 440.0, "D5": 587.33}


def build_score(T, tl):
    buf = np.zeros((int(T * SR), 2))
    rupture = tl["rupture"]
    S = tl["sections"]
    r0, l0, a0, b0, t0 = S["rise"][0], S["legacy"][0], S["assassination"][0], S["bogotazo"][0], S["title"][0]

    # 0-4.2 hook: D drone swell
    place(buf, bowed(NOTE["D2"], 4.6, 0.22, attack=1.2, release=1.0), 0.0, pan=-0.2)
    place(buf, bowed(NOTE["A2"], 4.4, 0.12, attack=1.6, release=1.0), 0.2, pan=0.25)
    place(buf, bowed(NOTE["D1"], 4.6, 0.20, attack=0.3, release=1.2, bright=0.4), 0.0)

    # rise: low-string ostinato + quiet tiple in 6/8 (bambuco-like lilt)
    beat = 60 / 84  # dotted-quarter pulse
    prog = [("D2", "F3", "A3"), ("Bb2", "D3", "F3"), ("G2", "Bb3", "D4"), ("A2", "C#4", "E4")]
    t = r0
    bars = max(1, round((l0 - r0) / (beat * 2)))
    for bar in range(bars):
        root, m3, p5 = prog[bar % 4]
        place(buf, bowed(NOTE[root], beat * 2.1, 0.20, attack=0.25, release=0.5), t, pan=-0.25)
        place(buf, bowed(NOTE[m3], beat * 2.1, 0.07, attack=0.4, release=0.6), t, pan=0.3)
        # tiple: 6 eighths per bar, accents on 1, 3(.), 5 for the bambuco feel
        e8 = beat / 3
        pattern = [(0, p5, 0.9), (2, m3, 0.6), (3, p5, 0.75), (5, m3, 0.55)]
        for k, nt, g in pattern:
            f = NOTE[nt] * (2 if NOTE[nt] < 200 else 1)
            place(buf, pluck(f, 1.1, 0.07 * g), t + k * e8, pan=0.45)
        t += beat * 2
    # legacy: timpani pulse + brass swells, build
    t = l0
    i = 0
    while t < a0 - 0.2:
        root, m3, p5 = prog[i % 4]
        place(buf, bowed(NOTE[root], beat * 2.1, 0.24, attack=0.15, release=0.5), t, pan=-0.25)
        place(buf, bowed(NOTE[p5] / 2, beat * 2.1, 0.10, attack=0.2, release=0.5), t, pan=0.2)
        place(buf, timpani(NOTE[root] if NOTE[root] < 100 else NOTE[root] / 2, 0.30 + 0.05 * i), t)
        if i >= 2:
            place(buf, timpani(NOTE["A1"], 0.16), t + beat * 1.5)
        t += beat * 2
        i += 1
    place(buf, brass(NOTE["D3"], 3.8, 0.10, attack=1.6, release=1.2), a0 - 3.4, pan=-0.15)
    place(buf, brass(NOTE["A3"], 3.6, 0.07, attack=1.8, release=1.2), a0 - 3.2, pan=0.2)
    place(buf, brass(NOTE["F3"], 3.6, 0.06, attack=1.9, release=1.2), a0 - 3.1, pan=0.05)

    # assassination up to the rupture: thinned out, heartbeat-like low pulse, rising tension
    place(buf, bowed(NOTE["D2"], rupture - a0 + 0.3, 0.18, attack=0.4, release=0.08, bright=0.35), a0 - 0.2)
    place(buf, bowed(NOTE["D4"], rupture - a0 - 0.1, 0.035, attack=2.0, release=0.08, vib=0.007), a0 + 0.1, pan=0.3)
    place(buf, bowed(NOTE["E4"] * 0.99, rupture - a0 - 1.1, 0.025, attack=1.6, release=0.08, vib=0.008), a0 + 1.1, pan=-0.3)
    tt = a0 + 0.1
    while tt < rupture - 0.3:
        place(buf, timpani(NOTE["D2"] / 2, 0.20, decay=0.5), tt)
        place(buf, timpani(NOTE["D2"] / 2, 0.11, decay=0.4), tt + 0.26)
        tt += 0.95
    # after rupture: near silence, then a thin, high, unresolved tone
    place(buf, bowed(NOTE["A4"], 3.1, 0.022, attack=1.2, release=1.4, bright=0.25, vib=0.003), rupture + 0.85, pan=0.15)
    place(buf, bowed(NOTE["D3"], 2.4, 0.05, attack=1.0, release=1.0, bright=0.3), rupture + 1.45, pan=-0.2)

    # bogotazo: full low chord, timpani rolls, then final note
    for nt, g, pn in (("D1", 0.20, 0), ("D2", 0.24, -0.25), ("A2", 0.14, 0.25), ("F3", 0.07, 0.35), ("D3", 0.10, -0.1)):
        place(buf, bowed(NOTE[nt], 4.6, g, attack=0.35, release=1.0), b0, pan=pn)
    place(buf, brass(NOTE["D3"], 4.2, 0.12, attack=0.8, release=1.2), b0 + 0.2, pan=-0.1)
    place(buf, brass(NOTE["A3"], 4.0, 0.08, attack=1.0, release=1.2), b0 + 0.4, pan=0.15)
    for k in range(5):
        place(buf, timpani(NOTE["D2"], 0.22 - 0.03 * k), b0 + k * beat)
    # final haunting note: lone tiple + low string D, long tail
    place(buf, bowed(NOTE["D2"], 2.6, 0.17, attack=0.3, release=1.9, bright=0.4), t0 - 0.4)
    place(buf, bowed(NOTE["A2"], 2.4, 0.07, attack=0.5, release=1.8, bright=0.4), t0 - 0.3, pan=0.2)
    place(buf, pluck(NOTE["D4"], 2.4, 0.07, damping=0.998), t0 + 0.35, pan=0.35)
    place(buf, pluck(NOTE["A3"], 2.2, 0.05, damping=0.998), t0 + 0.65, pan=0.35)
    return reverb(buf, wet=0.32)


def build_sfx(T, tl):
    buf = np.zeros((int(T * SR), 2))
    proj = projector(T)
    # projector bed under the archival sections, dropping out at the rupture
    g = np.ones(len(proj))
    r0 = int(tl["rupture"] * SR)
    g[r0:r0 + int(2.5 * SR)] = 0.0
    g[r0 + int(2.5 * SR):] = 0.6
    place(buf, lp(proj * g, 6000), 0.0, gain=1.0)
    for ev in tl["events"]:
        t, ty = ev["t"], ev["type"]
        if ty == "impact_low":
            place(buf, impact(0.75, 52, 30, 3.5), t)
        elif ty == "impact_soft":
            place(buf, impact(0.35, 70, 40, 2.0, noise=0.2), t)
        elif ty == "impact_big":
            place(buf, impact(0.9, 60, 28, 4.0, noise=0.6), t)
            place(buf, fire(T - t, 0.10), t + 0.1, pan=0.0)
            place(buf, crowd(T - t - 0.3, 0.22)[:, 0], t + 0.3, pan=-0.5)
        elif ty == "paper_slide":
            place(buf, paper(0.5, 0.18), t, pan=rng.uniform(-0.3, 0.3))
        elif ty == "typewriter":
            tt = t
            for _ in range(ev.get("chars", 8)):
                place(buf, typewriter_key(), tt, gain=0.22, pan=0.15)
                tt += rng.uniform(0.07, 0.13)
        elif ty == "rupture":
            # restrained: one muffled low thud and a paper tear, no gunshot recreation
            place(buf, lp(impact(0.6, 45, 26, 2.5, noise=0.5), 220), t)
            place(buf, paper(0.35, 0.30), t + 0.02)
    # distant crowd under "Multitudes lo seguían"
    c = crowd(4.2, 0.14)
    i = int(tl["lines"][5]["target"] * SR - 0.4 * SR)
    fade = np.minimum(1, np.minimum(np.arange(len(c)) / (0.8 * SR), (len(c) - np.arange(len(c))) / (1.2 * SR)))
    buf[i:i + len(c)] += c * fade[:, None]
    return reverb(buf, wet=0.18)


# ---------------------------------------------------------------- narration
def scratch_tts(text, path, model):
    cmd = [sys.executable, "-m", "piper", "-m", model, "-f", str(path),
           "--length-scale", "0.93", "--sentence-silence", "0.0"]
    subprocess.run(cmd, input=text.encode("utf-8"), check=True, capture_output=True)


def trim_silence(x, thresh=0.012):
    a = np.abs(x)
    idx = np.where(signal.convolve(a, np.ones(240) / 240, mode="same") > thresh)[0]
    if len(idx) == 0:
        return x
    s, e = max(idx[0] - 480, 0), min(idx[-1] + 2400, len(x))
    return x[s:e]


def process_voice(x):
    x = hp(x, 75, order=2)
    # gentle presence lift and mud cut via peaking-ish filters
    x = x + 0.25 * bp(x, 2500, 5000) - 0.18 * bp(x, 220, 420)
    # simple RMS compressor, ~3:1 above -20 dBFS
    win = int(0.02 * SR)
    rms = np.sqrt(signal.convolve(x ** 2, np.ones(win) / win, mode="same") + 1e-9)
    thr = db(-20)
    gain = np.where(rms > thr, (thr * (rms / thr) ** (1 / 3)) / rms, 1.0)
    gain = signal.convolve(gain, np.ones(win) / win, mode="same")
    x = x * gain
    return x / (np.abs(x).max() + 1e-9) * db(-3)


def build_narration(T, tl, model):
    buf = np.zeros(int(T * SR))
    ndir = ROOT / "assets" / "audio" / "narration"
    timing = []
    prev_end = 0.0
    source = "professional"
    with tempfile.TemporaryDirectory() as td:
        for ln in tl["lines"]:
            f = ndir / f"{ln['id']}.wav"
            if not f.exists():
                if not model:
                    raise SystemExit(f"missing {f} and no --scratch-voice model given")
                source = "scratch"
                f = Path(td) / f"{ln['id']}.wav"
                scratch_tts(ln["spoken"], f, model)
            x = process_voice(trim_silence(read_wav(f)))
            start = max(ln["target"], prev_end + 0.12)
            i = int(start * SR)
            x = x[: len(buf) - i]
            buf[i:i + len(x)] += x
            end = start + len(x) / SR
            timing.append({"id": ln["id"], "start": round(start, 3), "end": round(end, 3), "sub": ln["sub"]})
            prev_end = end
    return buf, timing, source


def duck(music, voice, depth_db=-10, attack=0.08, release=0.45):
    env = np.abs(voice)
    env = signal.convolve(env, np.ones(int(0.03 * SR)) / int(0.03 * SR), mode="same")
    active = (env > db(-38)).astype(float)
    g = np.ones_like(active)
    a, r = 1 / (attack * SR), 1 / (release * SR)
    target = 1 - active * (1 - db(depth_db))
    cur = 1.0
    for i in range(len(g)):  # one-pole smoothing with separate attack/release
        k = a if target[i] < cur else r
        cur += (target[i] - cur) * min(1, k * 4)
        g[i] = cur
    return music * g[:, None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch-voice", help="piper .onnx model used when pro narration is missing")
    args = ap.parse_args()
    tl = json.loads((ROOT / "production" / "timeline.json").read_text())
    T = tl["duration"]
    OUT.mkdir(exist_ok=True)

    voice, timing, vsource = build_narration(T, tl, args.scratch_voice)
    mfile = ROOT / "assets" / "audio" / "music.wav"
    if mfile.exists():
        m = read_wav(mfile)[: int(T * SR)]
        music = np.stack([m, m], axis=1)
        music = np.pad(music, ((0, int(T * SR) - len(music)), (0, 0)))
        msource = "external"
    else:
        music = build_score(T, tl)
        msource = "synthesized"
    sfx = build_sfx(T, tl)

    # phone speakers: cut sub rumble, lift the score's mids so it survives small drivers
    music = hp(music.T, 42, order=4).T
    if msource == "synthesized":
        music = music + 1.6 * bp(music.T, 280, 2200).T
    sfx = hp(sfx.T, 32, order=4).T
    music = music / (np.abs(music).max() + 1e-9) * db(-6)
    sfx = sfx / (np.abs(sfx).max() + 1e-9) * db(-8)
    music_d = duck(music, voice)
    v2 = np.stack([voice, voice], axis=1)
    mix = v2 * db(0) + music_d * db(-5) + sfx * db(-4)
    # final fade on the last 0.6 s so nothing cuts off abruptly
    n = len(mix)
    f = np.ones(n)
    f[n - int(0.6 * SR):] = np.linspace(1, 0, int(0.6 * SR)) ** 2
    mix *= f[:, None]
    mix = mix / (np.abs(mix).max() + 1e-9) * db(-1.5)

    write_wav(OUT / "narration.wav", voice)
    write_wav(OUT / "music.wav", music)
    write_wav(OUT / "sfx.wav", sfx)
    write_wav(OUT / "mix_premaster.wav", mix)
    # loudness to TikTok-friendly -14 LUFS, true peak -1.5 dBTP
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT / "mix_premaster.wav"),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "2",
                    str(OUT / "mix.wav")], check=True)
    meta = {"narration_source": vsource, "music_source": msource, "lines": timing}
    (OUT / "narration_timing.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
