#!/usr/bin/env python3
"""Build production/timeline.json and out/subtitulos.srt from the script.

The narration is recorded later by the author, so line timing is planned from
a syllable count at a natural documentary pace (RATE syllables per second)
plus short pauses at commas and full stops. Every scene cue in the renderer
and the sound design is anchored to these line starts, so changing a line
here (or setting measured "start"/"end" values after recording) re-flows the
whole piece.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATE = 6.2          # syllables per second, measured narration pace target
COMMA = 0.14        # pause after a comma (s)
STOP = 0.22         # pause after an internal full stop (s)
GAP = 0.28          # minimum breath between lines (s)
TAIL = 2.1          # time after the last line (title card)

# (id, subtitle text, spoken text or None, earliest start, red keywords)
LINES = [
    ("L01", "1948. | Liberales y conservadores | ya se enfrentan.",
     "Mil novecientos cuarenta y ocho. Liberales y conservadores ya se enfrentan.",
     0.55, ["1948"]),
    ("L02", "El 9 de abril asesinan en Bogotá | a Jorge Eliécer Gaitán, líder liberal.",
     "El nueve de abril asesinan en Bogotá a Jorge Eliécer Gaitán, líder liberal.",
     4.9, ["9 de abril", "Jorge Eliécer Gaitán"]),
    ("L03", "Linchan al tirador, Juan Roa Sierra.", None, 9.5, []),
    ("L04", "Si alguien más lo ordenó, nunca se probó.", None, 11.6, []),
    ("L05", "Bogotá arde.", None, 14.0, ["Bogotá"]),
    ("L06", "El Bogotazo se apaga en días. La Violencia, no.", None, 15.6, ["La Violencia"]),
    ("L07", "En el campo, ser liberal o conservador puede costar la vida.", None, 18.9, []),
    ("L08", "Cada región vive su propia guerra.", None, 22.6, []),
    ("L09", "Los muertos se estiman | entre decenas de miles | y más de doscientos mil.", None, 25.6, []),
    ("L10", "Cientos de miles de campesinos huyen.", None, 29.6, []),
    ("L11", "En 1958, los partidos pactan el Frente Nacional.",
     "En mil novecientos cincuenta y ocho, los partidos pactan el Frente Nacional.",
     32.0, ["1958", "Frente Nacional"]),
    ("L12", "Frena la guerra partidista, no el problema de la tierra.", None, 36.0, ["la tierra"]),
    ("L13", "En los sesenta, en esas regiones, | nacen nuevas guerrillas.", None, 39.6, []),
    ("L14", "¿Qué pasa cuando un país cierra una guerra sin cerrar sus causas?", None, 43.4,
     ["sin cerrar sus causas"]),
]

MAX_CHUNK = 40      # characters per subtitle event (at most two lines on screen)


def syllables(word):
    w = re.sub(r"[^a-záéíóúüñ]", "", word.lower())
    return max(1, len(re.findall(r"[iuü]?[aeoáéó][iu]?|[iu]+|[íú]", w))) if w else 0


def speech_seconds(text):
    s = sum(syllables(w) for w in text.split())
    return s / RATE + text.count(",") * COMMA + len(re.findall(r"[.?!] ", text)) * STOP


def split_chunks(text):
    """Split a line into subtitle events at sentence ends, then commas."""
    def split(p):
        if len(p) <= MAX_CHUNK:
            return [p]
        cuts = [m.end() for m in re.finditer(r",\s", p)]
        cuts = [c for c in cuts if 10 < c < len(p) - 8]
        if not cuts:  # cut at the space nearest the middle
            mid = len(p) // 2
            spaces = [m.start() for m in re.finditer(" ", p)]
            c = min(spaces, key=lambda s: abs(s - mid)) + 1
        else:
            c = min(cuts, key=lambda c: abs(c - len(p) / 2))
        return split(p[:c].strip()) + split(p[c:].strip())

    if "|" in text:  # explicit breaks written in the script
        return [p.strip() for p in text.split("|")]
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", text) if p.strip()]
    return [c for p in parts for c in split(p)]


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    lines, prev_end = [], 0.0
    for lid, sub_raw, spoken, earliest, red in LINES:
        sub = re.sub(r"\s*\|\s*", " ", sub_raw)
        spoken = spoken or sub
        start = max(earliest, prev_end + GAP)
        dur = speech_seconds(spoken)
        end = start + dur
        chunks, t = [], start
        sub_chunks = split_chunks(sub_raw)
        weights = [max(speech_seconds(c), 0.5) for c in sub_chunks]
        for c, w in zip(sub_chunks, weights):
            d = dur * w / sum(weights)
            chunks.append({"text": c, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
        lines.append({"id": lid, "sub": sub, "spoken": spoken, "start": round(start, 3),
                      "end": round(end, 3), "red": red, "chunks": chunks})
        prev_end = end
    duration = round(prev_end + TAIL, 2)
    tl = {"fps": 30, "width": 1080, "height": 1920, "duration": duration,
          "rate_syllables_per_s": RATE, "lines": lines}
    (ROOT / "production" / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))

    # SRT: chunks hold on screen until the next one starts (max +0.6 s) for readability
    events = [c for l in lines for c in l["chunks"]]
    rows = []
    for i, c in enumerate(events):
        nxt = events[i + 1]["start"] if i + 1 < len(events) else duration
        end = min(max(c["end"], c["start"] + 1.0) + 0.35, nxt - 0.04)
        c["show_end"] = round(end, 3)
        rows.append(f"{i + 1}\n{srt_time(c['start'])} --> {srt_time(end)}\n{c['text']}\n")
    (ROOT / "production" / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "subtitulos.srt").write_text("\n".join(rows), encoding="utf-8")

    for l in lines:
        print(f"{l['id']} {l['start']:6.2f}-{l['end']:6.2f}  {l['sub']}")
        for c in l["chunks"]:
            print(f"      {c['start']:6.2f}-{c['show_end']:6.2f}  {c['text']}")
    words = sum(len(l["sub"].split()) for l in lines)
    speech = sum(l["end"] - l["start"] for l in lines)
    print(f"duration {duration:.2f}s · speech {speech:.1f}s · {words} words · {len(events)} subtitle events")


if __name__ == "__main__":
    main()
