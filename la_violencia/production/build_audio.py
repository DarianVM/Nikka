#!/usr/bin/env python3
"""Original score and sound design, synthesized in code. No voice of any kind.

The bed is built to sit under the author's own narration:
  * music is low-passed and carries a dip at 1-4 kHz (the voice's presence band);
  * music is pre-ducked by DUCK_DB during every planned narration line;
  * the bed is normalized to BED_LUFS so a voice mixed at about -16 LUFS
    lands on top without fighting it.

Outputs (48 kHz, 16-bit stereo WAV) in out/:
  musica.wav, efectos.wav           stems
  mezcla_sin_voz.wav                music + effects, the track muxed into the MP4
  mezcla_con_voz.wav                only if assets/voz/narracion.wav exists
Every cue time comes from render_video.py, so sound and picture stay in sync.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_video as rv  # noqa: E402  (cue times and timeline)

SR = 48000
ROOT = rv.ROOT
OUT = ROOT / "out"
DUR = rv.DUR
N = int(DUR * SR)
DUCK_DB = -5.0
BED_LUFS = -20.0
rng = np.random.default_rng(1948)


# ---------------------------------------------------------------- dsp helpers
def sos(kind, f, order=2):
    return signal.butter(order, f, btype=kind, fs=SR, output="sos")


def lp(x, f, o=2):
    return signal.sosfilt(sos("low", f, o), x, axis=0)


def hp(x, f, o=2):
    return signal.sosfilt(sos("high", f, o), x, axis=0)


def bp(x, lo, hi, o=2):
    return signal.sosfilt(sos("band", [lo, hi], o), x, axis=0)


def env(n, a, r, curve=2.0):
    e = np.ones(n)
    na, nr = min(int(a * SR), n), min(int(r * SR), n)
    if na:
        e[:na] = np.linspace(0, 1, na) ** curve
    if nr:
        e[n - nr:] *= np.linspace(1, 0, nr) ** curve
    return e


def decay(n, tau):
    return np.exp(-np.arange(n) / SR / tau)


def place(buf, clip, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= len(buf) or i + len(clip) <= 0:
        return
    if i < 0:
        clip, i = clip[-i:], 0
    clip = clip[: len(buf) - i]
    th = (pan + 1) * np.pi / 4
    buf[i:i + len(clip), 0] += clip * gain * np.cos(th) * np.sqrt(2)
    buf[i:i + len(clip), 1] += clip * gain * np.sin(th) * np.sqrt(2)


def reverb(x, seconds=2.8, wet=0.28, damp=2.6):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    y = np.zeros_like(x)
    for c in range(2):
        ir = lp(rng.standard_normal(n), 4200) * np.exp(-damp * t)
        ir[: int(0.015 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        y[:, c] = signal.fftconvolve(x[:, c], ir)[: len(x)]
    return x * (1 - wet) + y * wet


def db(v):
    return 10 ** (v / 20)


# ---------------------------------------------------------------- instruments
def strings(freq, dur, amp, a=1.5, r=2.0, bright=0.55):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for det in (-0.004, 0.0, 0.0035):
        f = freq * (1 + det) * (1 + 0.003 * np.sin(2 * np.pi * (4.8 + det * 50) * t + rng.uniform(0, 6)))
        ph = 2 * np.pi * np.cumsum(f) / SR
        for h in range(1, 12):
            if freq * h > 7000:
                break
            out += np.sin(h * ph) * bright ** (h - 1) / h
    return lp(out, min(900 + freq * 5, 5000)) * env(n, a, r) * amp / 3


def harmonic(freq, dur, amp, a=2.0, r=2.5):
    """Thin high string harmonic: sine plus air, slow tremolo."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * freq * t) * (1 + 0.15 * np.sin(2 * np.pi * 5.5 * t))
    x += 0.12 * bp(rng.standard_normal(n), freq * 0.9, min(freq * 1.4, 20000))
    return x * env(n, a, r) * amp


def pulse(freq=55.0, amp=0.5, tau=0.35):
    """Soft low drum pulse (felt mallet on a bass drum)."""
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 0.6 * np.exp(-t / 0.03))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * decay(n, tau)
    x += 0.15 * lp(rng.standard_normal(n), 300) * decay(n, 0.05)
    return x * amp


def piano(freq, amp=0.18, tau=2.2):
    n = int(4 * SR)
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * freq * h * (1 + 0.0004 * h * h) * t) * decay(n, tau / h ** 0.7) / h ** 1.4
            for h in range(1, 8))
    x *= env(n, 0.004, 0.5)
    return lp(x, 3200) * amp


# ---------------------------------------------------------------- effects
def press_stamp(amp=0.9):
    """Dry thud of a hand press / rubber stamp: low body + wooden click."""
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * np.cumsum(70 * (1 + 1.5 * np.exp(-t / 0.02))) / SR) * decay(n, 0.12)
    click = bp(rng.standard_normal(n), 900, 4000) * decay(n, 0.012)
    thud = lp(rng.standard_normal(n), 400) * decay(n, 0.05)
    return (body * 0.9 + click * 0.5 + thud * 0.6) * amp


def paper_slide(length=0.6, amp=0.3, lo=1500, hi=7000):
    n = int(length * SR)
    x = bp(rng.standard_normal(n), lo, hi)
    e = np.sin(np.linspace(0, np.pi, n)) ** 1.5
    grit = 1 + 0.6 * (rng.random(n // 200 + 1).repeat(200)[:n] > 0.7)
    return x * e * grit * amp


def paper_tear(length=0.55, amp=0.45):
    n = int(length * SR)
    x = bp(rng.standard_normal(n), 800, 9000)
    crackle = (rng.random(n) > 0.985) * rng.standard_normal(n) * 3
    e = np.linspace(0.4, 1, n) * env(n, 0.01, 0.12)
    return (x + bp(crackle, 1500, 8000)) * e * amp


def type_key(amp=0.25):
    n = int(0.09 * SR)
    x = bp(rng.standard_normal(n), 1800, 6000) * decay(n, 0.006)
    x += np.sin(2 * np.pi * 180 * np.arange(n) / SR) * decay(n, 0.01) * 0.5
    return x * amp * rng.uniform(0.7, 1.0)


def tick(amp=0.25, f=1400):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * t) * decay(n, 0.02) + 0.3 * bp(rng.standard_normal(n), 2000, 6000)
            * decay(n, 0.004)) * amp


def low_hit(amp=0.8, f0=48, length=3.5):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * np.cumsum(f0 * (1 + 0.8 * np.exp(-t / 0.06))) / SR) * decay(n, 0.9)
    x += lp(rng.standard_normal(n), 180) * decay(n, 0.25) * 0.5
    return x * amp


def whoosh(length=2.2, amp=0.25, f0=300, f1=2500):
    n = int(length * SR)
    x = rng.standard_normal(n)
    out = np.zeros(n)
    seg = 2400
    for i in range(0, n, seg):
        p = i / n
        fc = f0 + (f1 - f0) * np.sin(p * np.pi / 2)
        out[i:i + seg] = bp(x[i:i + seg + 600], fc * 0.7, fc * 1.3)[:len(out[i:i + seg])]
    return lp(out, 6000) * np.sin(np.linspace(0, np.pi, n)) ** 2 * amp


def fire_bed(length, amp=0.12):
    n = int(length * SR)
    roar = lp(rng.standard_normal(n), 500) * (0.7 + 0.3 * np.sin(np.linspace(0, 9, n)))
    crack = np.zeros(n)
    for _ in range(int(length * 14)):
        i = rng.integers(0, n - 2000)
        crack[i:i + 2000] += bp(rng.standard_normal(2000), 1500, 6000) * decay(2000, 0.004) * rng.uniform(0.3, 1)
    return (roar * 0.8 + crack * 0.7) * env(n, 0.3, 0.9) * amp


def crowd_far(length, amp=0.07):
    """Distant, indistinct crowd: band-limited noise with slow swells (no words)."""
    n = int(length * SR)
    x = bp(rng.standard_normal(n), 250, 1200, 3)
    mod = lp(rng.standard_normal(n), 2) * 40
    return x * (0.6 + 0.4 * np.tanh(mod)) * env(n, 0.5, 1.0) * amp


def wind(length, amp=0.08):
    n = int(length * SR)
    x = rng.standard_normal(n)
    a = bp(x, 200, 900) * (0.6 + 0.4 * np.sin(np.linspace(0, 5, n)))
    b = bp(x, 1500, 3500) * 0.2 * (0.5 + 0.5 * np.sin(np.linspace(0, 11, n) + 1))
    return (a + b) * env(n, 0.6, 0.8) * amp


# ---------------------------------------------------------------- score
D2, A2, F2, C3, D3, E3, F3, A3, D4, F4, A4, D5, A5 = 73.42, 110.0, 87.31, 130.81, 146.83, 164.81, 174.61, \
    220.0, 293.66, 349.23, 440.0, 587.33, 880.0


def build_music():
    m = np.zeros((N, 2))
    # Scene 1-2: low drone that tightens toward the assassination
    place(m, strings(D2, rv.FIRE + 0.4, 0.22, a=2.5, r=1.2), 0.0, pan=-0.2)
    place(m, strings(A2, rv.FIRE - 1.0, 0.13, a=3.0, r=1.5), 1.5, pan=0.25)
    place(m, harmonic(A5, rv.FIRE - rv.S2 + 0.5, 0.018, a=1.5, r=0.6), rv.S2)
    # sparse piano motif on the newspaper: D - F - A (minor, unresolved)
    for t, f in ((ls_("L02") + 0.15, D4), (ls_("L02") + 1.3, F4), (ls_("L02") + 2.6, A3)):
        place(m, piano(f, 0.11), t, pan=0.1)
    # Bogotazo: one dark chord, no "action" percussion
    place(m, strings(D2, 4.0, 0.30, a=0.05, r=2.5, bright=0.7), rv.FIRE)
    place(m, strings(F2, 4.0, 0.16, a=0.1, r=2.5), rv.FIRE, pan=-0.3)
    place(m, strings(C3, 4.0, 0.12, a=0.2, r=2.5), rv.FIRE, pan=0.3)
    # Scenes 3-4: steady, restrained pulse (≈ 66 bpm) under the map and the numbers
    beat = 60 / 66
    t = rv.S3 + 0.2
    i = 0
    while t < rv.S5 - 0.4:
        place(m, pulse(55 if i % 4 else 49, 0.30 if i % 4 == 0 else 0.18), t)
        t += beat
        i += 1
    place(m, strings(D2, rv.S5 - rv.S3, 0.17, a=2.0, r=1.5), rv.S3)
    place(m, strings(A2, rv.S5 - rv.S3 - 2, 0.10, a=3.0, r=1.5), rv.S3 + 1.5, pan=0.3)
    place(m, strings(E3, rv.FN - rv.S4, 0.07, a=2.5, r=1.2), rv.S4, pan=-0.35)     # tension over the dead
    place(m, strings(F3, rv.S5 - rv.FN, 0.07, a=1.5, r=1.5), rv.FN, pan=0.35)
    place(m, harmonic(D5, rv.S5 - rv.S3, 0.012, a=3, r=2), rv.S3 + 1.0, pan=-0.1)
    # Scene 5: thinner; drops to silence before the question
    place(m, strings(D2, rv.Q - rv.S5 + 0.6, 0.18, a=0.8, r=0.5), rv.S5 - 0.3)
    place(m, strings(A2, rv.Q - rv.S5 + 0.6, 0.10, a=0.8, r=0.5), rv.S5 - 0.3, pan=0.3)
    place(m, harmonic(A4, DUR - rv.Q - 0.4, 0.016, a=1.2, r=2.0), rv.Q + 0.4)
    # title: a low D and a lone piano note, long tail
    place(m, strings(D2, DUR - rv.TITLE + 0.2, 0.2, a=0.6, r=1.4), rv.TITLE - 0.1)
    place(m, piano(D3, 0.14, tau=3.0), rv.TITLE + 0.05)
    m = reverb(m, wet=0.32)
    # leave room for the voice: low-pass and a soft dip at 1-4 kHz
    m = lp(m, 5200)
    m = m - 0.5 * bp(m, 1000, 4000)
    return hp(m, 35)


def ls_(i):
    return rv.ls(i)


def build_sfx():
    s = np.zeros((N, 2))
    l1, l2 = rv.ls("L01"), rv.ls("L02")
    place(s, press_stamp(0.9), 0.15)
    place(s, low_hit(0.35, 44, 2.5), 0.15)
    place(s, paper_slide(0.45, 0.22), l1 + 0.85, pan=-0.5)
    place(s, paper_slide(0.45, 0.22), l1 + 1.2, pan=0.5)
    place(s, paper_slide(0.8, 0.35, 900, 6000), l2 - 0.3)
    for k in range(16):  # headline types in
        place(s, type_key(0.20), l2 + 0.25 + k * 0.032, pan=rng.uniform(-0.2, 0.2))
    place(s, press_stamp(1.0), l2 + 0.15)
    place(s, paper_tear(0.6, 0.5), rv.S2)
    for k in range(24):
        place(s, type_key(0.17), rv.S2 + 0.3 + k * 0.042, pan=-0.15)
    for k in range(14):
        place(s, type_key(0.17), rv.S2 + 1.2 + k * 0.05, pan=-0.15)
    place(s, tick(0.18, 900), rv.ls("L03"))
    place(s, low_hit(0.30, 52, 2.0), rv.ls("L04"))
    place(s, low_hit(0.75, 42, 4.0), rv.FIRE)
    place(s, fire_bed(rv.S3 + 0.9 - rv.FIRE, 0.11), rv.FIRE)
    place(s, crowd_far(rv.S3 + 0.9 - rv.FIRE + 0.5, 0.06), rv.FIRE - 0.3, pan=0.2)
    # map: camera pull-back, then one press thud per region
    place(s, whoosh(2.6, 0.22, 250, 1800), rv.S3 + 0.1)
    place(s, low_hit(0.4, 46, 3.0), rv.ls("L06") + 1.9)
    for i, rt in enumerate(rv.region_times()):
        place(s, press_stamp(0.42), rt, pan=(-0.4 if rv.REGION_CARDS[i][6 - 1] == "l" else 0.4) * 0)
        place(s, paper_slide(0.3, 0.08, 2000, 7000), rt + 0.12, pan=0.3)
    place(s, paper_slide(0.9, 0.12, 1200, 5000), rv.region_times()[0] + 0.5, pan=0.2)   # dashed flight route
    # consequences
    place(s, paper_slide(0.7, 0.32, 900, 6000), rv.S4 - 0.1)
    t0 = rv.ls("L09") + 0.3
    for i in range(3):
        place(s, tick(0.22, 1100 - i * 150), t0 + i * 0.85)
    place(s, wind(rv.FN - rv.DISP + 0.6, 0.09), rv.DISP - 0.3)
    place(s, paper_slide(0.6, 0.25), rv.FN - 0.2)
    for i in range(3):
        place(s, tick(0.2, 800), rv.FN + i * 0.6)
    place(s, press_stamp(1.0), rv.FN + 1.4)
    for i in range(4):
        place(s, type_key(0.25), rv.FN + 1.7 + i * 0.15)
    place(s, paper_tear(0.35, 0.18), rv.PEND + 0.2)
    # sixties
    place(s, low_hit(0.45, 46, 3.0), rv.S5)
    place(s, tick(0.18, 700), rv.ls("L13") + 0.9)
    place(s, tick(0.18, 700), rv.ls("L13") + 1.6)
    for fx in (0.0, 0.3, 0.55):
        place(s, tick(0.15, 1200), rv.Q + 0.3 + 2.3 * (1 - (1 - fx) ** (1 / 3)))
    place(s, press_stamp(0.6), rv.Q + 2.5)
    place(s, low_hit(0.5, 40, 3.0), rv.TITLE)
    place(s, paper_slide(0.6, 0.12), rv.TITLE)
    return hp(reverb(s, seconds=1.4, wet=0.14, damp=4.5), 30)


def duck_curve():
    """Planned narration windows -> smooth gain curve for the music."""
    g = np.zeros(N)
    for l in rv.TL["lines"]:
        a, b = int((l["start"] - 0.15) * SR), int((l["end"] + 0.2) * SR)
        g[max(a, 0):min(b, N)] = 1
    k = int(0.18 * SR)
    g = np.convolve(g, np.ones(k) / k, mode="same")
    return db(DUCK_DB * g)


def limiter_gain(x, ceiling, look=0.003, release=0.12):
    from scipy.ndimage import minimum_filter1d
    peak = np.abs(x).max(axis=1)
    g = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    w = int(look * SR) * 2 + 1
    g = minimum_filter1d(g, w, origin=-(w // 2) + 1)          # react before the peak arrives
    a = np.exp(-1 / (release * SR))
    g = signal.lfilter([1 - a], [1, -a], g - 1) + 1            # smooth release toward unity
    g = np.minimum(g, minimum_filter1d(np.minimum(1.0, ceiling / np.maximum(peak, 1e-9)), w))
    return g[:, None]


def lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    summ = r[r.rfind("Summary:"):]
    I = float(summ.split("I:")[1].split("LUFS")[0])
    tp = float(summ.split("Peak:")[1].split("dBFS")[0])
    return I, tp


def write(path, x):
    wavfile.write(path, SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))


def main():
    OUT.mkdir(exist_ok=True)
    music = build_music() * duck_curve()[:, None]
    sfx = build_sfx()
    fade = np.ones(N)
    fade[-int(0.5 * SR):] = np.linspace(1, 0, int(0.5 * SR)) ** 2
    music *= fade[:, None]
    sfx *= fade[:, None]
    bed = music * 0.9 + sfx
    tmp = OUT / "_bed_tmp.wav"
    write(tmp, bed / max(1e-9, np.abs(bed).max()) * 0.5)
    I, _ = lufs(tmp)
    gain = db(BED_LUFS + 0.3 - I) * 0.5 / max(1e-9, np.abs(bed).max())   # +0.3 dB: limiter loss
    bed, music, sfx = bed * gain, music * 0.9 * gain, sfx * gain
    # look-ahead peak limiter on the transients (stamps, hits): keeps headroom for the voice
    g = limiter_gain(bed, db(-3.6))
    bed, music, sfx = bed * g, music * g, sfx * g
    write(OUT / "musica.wav", music)
    write(OUT / "efectos.wav", sfx)
    write(OUT / "mezcla_sin_voz.wav", bed)
    tmp.unlink()
    I, tp = lufs(OUT / "mezcla_sin_voz.wav")
    print(f"mezcla_sin_voz.wav: {I:.1f} LUFS integrated, true peak {tp:.1f} dBTP, {DUR:.2f} s")

    voice = ROOT / "assets" / "voz" / "narracion.wav"
    if voice.exists():                        # the author's own recorded narration
        sr, v = wavfile.read(voice)
        v = v.astype(np.float32) / (32768.0 if v.dtype == np.int16 else 1.0)
        if v.ndim == 2:
            v = v.mean(1)
        if sr != SR:
            v = signal.resample_poly(v, SR, sr)
        v = np.pad(v, (0, max(0, N - len(v))))[:N]
        vv = np.stack([v, v], 1)
        mix = bed + vv
        write(OUT / "mezcla_con_voz.wav", mix / max(1.0, np.abs(mix).max() / db(-1)))
        print("mezcla_con_voz.wav written (check loudness: voice target ≈ -16 LUFS)")
    meta = {"duration_s": DUR, "sample_rate": SR, "bed_lufs_target": BED_LUFS, "duck_db": DUCK_DB,
            "narration_windows": [[l["id"], l["start"], l["end"]] for l in rv.TL["lines"]]}
    (OUT / "audio_notes.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
